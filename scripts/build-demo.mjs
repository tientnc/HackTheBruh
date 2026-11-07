import { cp, mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';

const output = resolve(process.env.DEMO_BUILD_DIRECTORY || 'web/dist');
await mkdir(output, { recursive: true });
await cp(resolve('web/public'), output, { recursive: true });
// Whitelist public settings. An import/admin key is never emitted into the browser.
const url = (process.env.SUPABASE_URL || '').replace(/\/$/, '');
const key = process.env.SUPABASE_PUBLISHABLE_KEY || '';
if (url && !/^https:\/\/[a-z0-9-]+\.supabase\.co$/.test(url)) throw new Error('Expected an HTTPS Supabase project URL');
if (key.startsWith('sb_secret_')) throw new Error('An admin key cannot be a browser publishable key');
if (key.split('.').length === 3) {
  let payload;
  try { payload = JSON.parse(Buffer.from(key.split('.')[1], 'base64url').toString()); }
  catch { throw new Error('Invalid legacy public key'); }
  if (payload.role !== 'anon') throw new Error('Only a legacy anon key may be used in the browser');
}
if (Boolean(url) !== Boolean(key)) throw new Error('Supply both public Supabase settings, or neither for snapshot preview');
await writeFile(resolve(output, 'config.json'), JSON.stringify({ supabaseUrl: url, publishableKey: key }) + '\n');
console.log(`Demo built: ${output} (${url ? 'Supabase reads enabled' : 'snapshot preview'})`);
