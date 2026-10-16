import { describe, expect, it } from 'vitest';
import { evaluateUpdate } from '../../apps/desktop/src/main/updates';

const digest='a'.repeat(64);
const fixture = () => ({
  manifest: { version:'0.2.0', channel:'stable', sequence:2, minCompatibleVersion:'0.1.0', packageSha256:digest, targetSchema:4, compatibleRollbackSchemas:[4] },
  current: { version:'0.1.0', channel:'stable', sequence:1, schema:4 },
  observed: { packageSha256:digest, signatureStatus:'Valid', publisherThumbprint:'ABC', chainValid:true, timestampValid:true, testCertificate:false },
  trustedPublisherThumbprints:['ABC'], backup: { consistent:true, verified:true, schema:4, sha256:'b'.repeat(64) },
  checkpointsSaved:true,
});

describe('update preflight rejects untrusted bytes before any install', () => {
  it('accepts byte and identity matched preflight only', () => {
    expect(evaluateUpdate(fixture()).state).toBe('READY_FOR_EXTERNAL_INSTALL');
  });
  for (const failure of ['publisher','signature','chain','timestamp','testCertificate','tamper','replay','downgrade','backup','checkpoint']) {
    it(`rejects ${failure}`, () => {
      const value=fixture();
      if(failure==='publisher')value.observed.publisherThumbprint='ATTACKER';
      if(failure==='signature')value.observed.signatureStatus='NotSigned';
      if(failure==='chain')value.observed.chainValid=false;
      if(failure==='timestamp')value.observed.timestampValid=false;
      if(failure==='testCertificate')value.observed.testCertificate=true;
      if(failure==='tamper')value.observed.packageSha256='c'.repeat(64);
      if(failure==='replay')value.manifest.sequence=1;
      if(failure==='downgrade')value.manifest.version='0.0.1';
      if(failure==='backup')value.backup.verified=false;
      if(failure==='checkpoint')value.checkpointsSaved=false;
      expect(evaluateUpdate(value).state).toBe('REJECTED');
      expect(evaluateUpdate(value).activeVersion).toBe('0.1.0');
    });
  }
  it('does not use authorized rollback to admit a downloaded downgrade',()=>{
    const value={...fixture(),rollback:{authorized:true,localTrustedVersion:'0.0.1',savedPackageSha256:digest}};
    value.manifest.version='0.0.1';
    expect(evaluateUpdate(value).state).toBe('REJECTED');
  });
});
