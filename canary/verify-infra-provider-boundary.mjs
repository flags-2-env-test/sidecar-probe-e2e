#!/usr/bin/env node
import assert from 'node:assert/strict';
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';

const EXPECTED_ORG = 'flags-2-env';
const EXPECTED_SCHEMA = 'flags_2_env';
const EXPECTED_MERGE = 'b05f40645109dbbc4a735f672f269ac18bdbb6b7';
const providerEnv = {
  supabase: ['SUPABASE_AUTH_DATABASE_URL', 'SUPABASE_ADMIN_DATABASE_URL'],
  neon: ['NEON_AUTH_DATABASE_URL', 'NEON_ADMIN_DATABASE_URL']
};

function validateTopology(topology) {
  const errors = [];
  const check = (condition, message) => { if (!condition) errors.push(message); };
  check(topology?.contract === 'SharedAuthTopology' && topology?.version === 1, 'contract/version drift');
  check(topology?.githubOrg === EXPECTED_ORG, 'githubOrg drift');
  for (const [provider, [authEnv, adminEnv]] of Object.entries(providerEnv)) {
    const value = topology?.[provider] ?? {};
    check(value.runtimeOrg === EXPECTED_ORG && value.targetOrg === EXPECTED_ORG, `${provider} org drift`);
    check(value.placement === 'dedicated-org', `${provider} placement drift`);
    check(value.schema === EXPECTED_SCHEMA, `${provider} schema drift`);
    check(value.authDatabaseUrlEnv === authEnv && value.adminDatabaseUrlEnv === adminEnv, `${provider} env drift`);
    check(value.authDatabaseUrlEnv !== value.adminDatabaseUrlEnv, `${provider} credential crossover`);
  }
  const policy = topology?.requestPolicy ?? {};
  check(policy.requireBothProvidersConfigured === true, 'both providers must remain required');
  check(['availability-first', 'strict-paired'].includes(policy.customerMode), 'customer mode drift');
  check(policy.adminMode === 'strict-paired' && policy.sensitiveMode === 'strict-paired', 'admin/sensitive policy weakened');
  check(policy.rejectProviderDisagreement === true, 'provider disagreement no longer fail-closed');
  const source = JSON.stringify(topology);
  check(!source.includes('"DATABASE_URL"'), 'generic DATABASE_URL introduced');
  check(!/postgres(?:ql)?:\/\//i.test(source), 'database URL embedded');
  check(!/shared-org-schema|shared-organization-namespace/i.test(source), 'shared provider placement introduced');
  return errors;
}

function validateProviderPolicy(source, provider) {
  const policy = source.toLowerCase();
  const errors = [];
  if (!policy.includes('migration') || !policy.includes('secret')) errors.push(`${provider} policy incomplete`);
  // The pinned production documentation expresses dedicated ownership as
  // exact organization pairing. Accept that statement without relaxing the
  // independently checked structured topology or the shared-placement ban.
  const dedicated = policy.includes('dedicated') && policy.includes(EXPECTED_ORG);
  const exactPairing = policy.includes(`organization paired exactly with github org \`${EXPECTED_ORG}\``);
  if (!dedicated && !exactPairing) errors.push(`${provider} dedicated ownership not documented`);
  if (!policy.includes('shared-provider organization placement is forbidden') ||
      policy.includes('shared-provider organization fallback is allowed')) {
    errors.push(`${provider} shared provider placement is not forbidden`);
  }
  return errors;
}

export function verifyProductionRoot(root) {
  const errors = [];
  const check = (condition, message) => { if (!condition) errors.push(message); };
  const license = resolve(root, 'LICENSE');
  check(existsSync(license), 'LICENSE missing');
  if (existsSync(license)) check(readFileSync(license, 'utf8').startsWith('MIT License'), 'LICENSE is not MIT');

  const topologyPath = resolve(root, 'shared-auth/topology.json');
  check(existsSync(topologyPath), 'shared-auth topology missing');
  if (existsSync(topologyPath)) errors.push(...validateTopology(JSON.parse(readFileSync(topologyPath, 'utf8'))));

  for (const [provider, [authEnv, adminEnv]] of Object.entries(providerEnv)) {
    const readme = resolve(root, provider, 'README.md');
    check(existsSync(readme), `${provider}/README.md missing`);
    if (existsSync(readme)) {
      errors.push(...validateProviderPolicy(readFileSync(readme, 'utf8'), provider));
    }
    for (const [lane, expectedEnv] of [['auth', authEnv], ['admin', adminEnv]]) {
      const dir = resolve(root, provider, lane, 'migrations');
      check(existsSync(dir), `${provider}/${lane}/migrations missing`);
      if (!existsSync(dir)) continue;
      const sql = readdirSync(dir).filter((name) => name.endsWith('.sql'));
      check(sql.length > 0, `${provider}/${lane} has no reviewed SQL`);
      for (const name of sql) {
        const source = readFileSync(resolve(dir, name), 'utf8');
        check(!/postgres(?:ql)?:\/\//i.test(source), `${provider}/${lane}/${name} embeds a database URL`);
        check(!/(^|[^A-Z0-9_])DATABASE_URL([^A-Z0-9_]|$)/.test(source), `${provider}/${lane}/${name} uses generic DATABASE_URL`);
        check(source.includes(`'${expectedEnv}'`), `${provider}/${lane}/${name} does not record canonical env`);
        check(source.includes(`'${EXPECTED_ORG}','${EXPECTED_ORG}','${EXPECTED_ORG}'`), `${provider}/${lane}/${name} provider org metadata drift`);
      }
    }
  }
  return errors;
}

function selfTest(root) {
  const topology = JSON.parse(readFileSync(resolve(root, 'shared-auth/topology.json'), 'utf8'));
  assert.deepEqual(validateTopology(topology), []);
  const mutations = [
    ['shared-org', (t) => { t.supabase.runtimeOrg = 'oresoftware'; }],
    ['generic-db', (t) => { t.neon.authDatabaseUrlEnv = 'DATABASE_URL'; }],
    ['credential-crossover', (t) => { t.supabase.adminDatabaseUrlEnv = t.supabase.authDatabaseUrlEnv; }],
    ['weaken-admin', (t) => { t.requestPolicy.adminMode = 'availability-first'; }],
    ['accept-disagreement', (t) => { t.requestPolicy.rejectProviderDisagreement = false; }]
  ];
  for (const [name, mutate] of mutations) {
    const candidate = structuredClone(topology);
    mutate(candidate);
    assert.ok(validateTopology(candidate).length > 0, `${name} unexpectedly passed`);
  }
  let documentationNegativeCases = 0;
  for (const provider of Object.keys(providerEnv)) {
    const source = readFileSync(resolve(root, provider, 'README.md'), 'utf8');
    assert.deepEqual(validateProviderPolicy(source, provider), []);
    const dedicatedWording = source.replace('organization paired exactly with GitHub org', 'dedicated organization for GitHub org');
    assert.deepEqual(validateProviderPolicy(dedicatedWording, provider), []);
    const invalidDocs = [
      ['wrong-owner', source.replaceAll(EXPECTED_ORG, 'another-org')],
      ['inexact-pairing', source.replace('paired exactly', 'paired loosely')],
      ['shared-placement', source.replace('placement is forbidden', 'placement is allowed')],
      ['missing-placement-ban', source.replace('Shared-provider organization placement is forbidden.', '')],
      ['fallback-allowed', `${source}\nShared-provider organization fallback is allowed.`],
      ['missing-secret-policy', source.replaceAll('secret', 'ordinary')]
    ];
    for (const [name, candidate] of invalidDocs) {
      assert.ok(validateProviderPolicy(candidate, provider).length > 0, `${provider}/${name} unexpectedly passed`);
      documentationNegativeCases += 1;
    }
  }
  return { topologyNegativeCases: mutations.length, documentationNegativeCases };
}

const root = resolve(process.argv[2] ?? 'production-infra');
const errors = verifyProductionRoot(root);
if (errors.length) {
  for (const error of errors) console.error(`- ${error}`);
  process.exit(1);
}
const cases = selfTest(root);
console.log(JSON.stringify({ status: 'passed', productionRevision: EXPECTED_MERGE,
  negativeCases: cases.topologyNegativeCases + cases.documentationNegativeCases, ...cases }));
