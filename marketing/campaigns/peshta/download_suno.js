#!/usr/bin/env node
/**
 * Suno Audio Downloader & Decryptor
 * Supports share URLs (e.g. https://suno.com/s/...), song URLs (https://suno.com/song/...), or song IDs.
 */

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

async function downloadSunoTrack(urlOrId, outputDir = '.') {
  let clipId = urlOrId.trim();

  // If share link or full song link, resolve to clip ID
  if (clipId.includes('suno.com')) {
    const headRes = await fetch(clipId, {
      method: 'GET',
      headers: { 'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)' },
      redirect: 'follow'
    });
    const finalUrl = headRes.url;
    const match = finalUrl.match(/\/song\/([a-f0-9\-]{36})/);
    if (match) {
      clipId = match[1];
    } else {
      const match2 = clipId.match(/([a-f0-9\-]{36})/);
      if (match2) clipId = match2[1];
      else throw new Error(`Could not resolve clip ID from: ${urlOrId}`);
    }
  }

  console.log(`Processing Suno Clip ID: ${clipId}`);

  // Fetch song page HTML for metadata
  const pageRes = await fetch(`https://suno.com/song/${clipId}`, {
    headers: { 'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)' }
  });
  const pageHtml = await pageRes.text();

  // Extract song title
  let title = 'suno_track';
  const titleMatch = pageHtml.match(/<title>(.*?)<\/title>/);
  if (titleMatch) {
    title = titleMatch[1].replace(/ \| Suno.*$/, '').trim();
  }
  const cleanTitle = title.replace(/[^\w\s\-().]/gi, '_').replace(/\s+/g, '_');
  console.log(`Title: ${title}`);

  // Extract audio URL
  const audioMatch = pageHtml.match(/https:\/\/[^"'\s]+\.m4a/);
  if (!audioMatch) {
    throw new Error('Could not find .m4a audio stream URL in page HTML');
  }
  const audioUrl = audioMatch[0];
  console.log(`Audio stream: ${audioUrl}`);

  // 1. Fetch rights / license
  const timestamp = Date.now();
  const token = Buffer.from(JSON.stringify({ timestamp })).toString('base64');
  const browserToken = JSON.stringify({ token });

  const rightsRes = await fetch('https://studio-api-prod.suno.com/api/mango/rights', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
      'Origin': 'https://suno.com',
      'Referer': 'https://suno.com/',
      'Browser-Token': browserToken
    },
    body: JSON.stringify({
      content_params: {
        content_id: clipId,
        content_type: 'clip'
      }
    })
  });

  if (!rightsRes.ok) {
    throw new Error(`Rights endpoint returned ${rightsRes.status}: ${await rightsRes.text()}`);
  }

  const rights = await rightsRes.json();

  // 2. Derive userKey from glt (SHA-256)
  const enc = new TextEncoder().encode(rights.glt);
  const hash = await crypto.subtle.digest('SHA-256', enc);
  const userKey = await crypto.subtle.importKey('raw', hash, { name: 'AES-GCM' }, false, ['decrypt']);

  // 3. Decrypt content key
  const keyBytes = Buffer.from(rights.key, 'base64');
  const keyIv = keyBytes.subarray(0, 12);
  const keyData = keyBytes.subarray(12);
  const rawKey = await crypto.subtle.decrypt(
    {
      name: 'AES-GCM',
      iv: keyIv,
      additionalData: new TextEncoder().encode(clipId)
    },
    userKey,
    keyData
  );
  const aesCtrKey = await crypto.subtle.importKey('raw', rawKey, { name: 'AES-CTR' }, false, ['decrypt']);

  // 4. Decrypt content IV
  const ivBytes = Buffer.from(rights.iv, 'base64');
  const ivIv = ivBytes.subarray(0, 12);
  const ivData = ivBytes.subarray(12);
  const rawIv = await crypto.subtle.decrypt(
    {
      name: 'AES-GCM',
      iv: ivIv,
      additionalData: new TextEncoder().encode(clipId)
    },
    userKey,
    ivData
  );
  const iv = new Uint8Array(rawIv);

  // 5. Download encrypted media
  console.log('Downloading encrypted media stream...');
  const mediaRes = await fetch(audioUrl);
  if (!mediaRes.ok) throw new Error(`Media fetch failed with status: ${mediaRes.status}`);
  const encBuffer = Buffer.from(await mediaRes.arrayBuffer());

  // 6. AES-CTR decryption
  console.log('Decrypting audio stream...');
  const decBuffer = await crypto.subtle.decrypt(
    {
      name: 'AES-CTR',
      counter: iv,
      length: 128
    },
    aesCtrKey,
    encBuffer
  );

  const m4aPath = path.join(outputDir, `${cleanTitle}.m4a`);
  const mp3Path = path.join(outputDir, `${cleanTitle}.mp3`);

  fs.writeFileSync(m4aPath, Buffer.from(decBuffer));
  console.log(`Saved original audio (Opus M4A): ${m4aPath}`);

  // 7. Convert to MP3 using ffmpeg if available
  try {
    console.log('Converting to MP3...');
    execSync(`ffmpeg -y -i "${m4aPath}" -b:a 320k "${mp3Path}" 2>/dev/null`);
    console.log(`Saved universal audio (MP3 320k): ${mp3Path}`);
  } catch (err) {
    console.warn('ffmpeg not found or conversion failed, M4A preserved.');
  }

  return { m4aPath, mp3Path, title };
}

if (require.main === module) {
  const target = process.argv[2] || 'https://suno.com/s/V8VgPAiyCXW6SKVJ';
  const outDir = process.argv[3] || '.';
  downloadSunoTrack(target, outDir).catch(err => {
    console.error('Error:', err);
    process.exit(1);
  });
}

module.exports = { downloadSunoTrack };
