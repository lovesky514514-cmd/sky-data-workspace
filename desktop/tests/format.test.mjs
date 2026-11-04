import test from 'node:test';
import assert from 'node:assert/strict';
import { parseUrls, display, date } from '../src/format.ts';
test('来源去重且不接受本机文件、脚本或URL凭据', () => {
  assert.deepEqual(parseUrls('https://example.com/a\nhttps://example.com/a\n'), [
    'https://example.com/a',
  ]);
  for (const text of [
    'file:///c:/x',
    'javascript:alert(1)',
    'https://user:pass@example.com',
    'bad-url',
    '',
  ])
    assert.throws(() => parseUrls(text));
});
test('精确数值字符串不转成二进制浮点', () => {
  assert.equal(display('12345678901234567890.12'), '12345678901234567890.12');
  assert.equal(display(null), '—');
  assert.equal(date('invalid'), '—');
});
