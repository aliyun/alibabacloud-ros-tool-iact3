import assert from 'node:assert/strict';
import test from 'node:test';

import {
  getPreferredLocale,
  getLocaleRedirectUrl,
} from './localeRedirect.mjs';

const baseUrl = '/alibabacloud-ros-tool-iact3/';

test('uses the zh-cn locale for Chinese browser language variants', () => {
  assert.equal(getPreferredLocale(['zh-CN', 'en-US']), 'zh-cn');
  assert.equal(getPreferredLocale(['zh-Hans-CN', 'en-US']), 'zh-cn');
  assert.equal(getPreferredLocale(['zh']), 'zh-cn');
});

test('falls back to the default locale for unsupported browser languages', () => {
  assert.equal(getPreferredLocale(['fr-FR', 'de-DE']), 'en');
  assert.equal(getPreferredLocale([]), 'en');
});

test('redirects default-locale pages to the preferred localized page', () => {
  assert.equal(
    getLocaleRedirectUrl({
      baseUrl,
      languages: ['zh-CN'],
      pathname: '/alibabacloud-ros-tool-iact3/usage/test-run',
      search: '?from=docs',
      hash: '#reports',
    }),
    '/alibabacloud-ros-tool-iact3/zh-cn/usage/test-run?from=docs#reports',
  );
});

test('redirects the site root to the preferred localized root', () => {
  assert.equal(
    getLocaleRedirectUrl({
      baseUrl,
      languages: ['zh-CN'],
      pathname: '/alibabacloud-ros-tool-iact3/',
    }),
    '/alibabacloud-ros-tool-iact3/zh-cn/',
  );
});

test('does not redirect already-localized pages', () => {
  assert.equal(
    getLocaleRedirectUrl({
      baseUrl,
      languages: ['zh-CN'],
      pathname: '/alibabacloud-ros-tool-iact3/zh-cn/usage/test-run',
    }),
    null,
  );
});

test('does not redirect non-Chinese browsers or URLs outside the site base', () => {
  assert.equal(
    getLocaleRedirectUrl({
      baseUrl,
      languages: ['en-US'],
      pathname: '/alibabacloud-ros-tool-iact3/usage/test-run',
    }),
    null,
  );
  assert.equal(
    getLocaleRedirectUrl({
      baseUrl,
      languages: ['zh-CN'],
      pathname: '/other-site/usage/test-run',
    }),
    null,
  );
});
