/** Preflight only. Native signing observations must come from the main process.
 * No renderer IPC or downloaded manifest can provide signature authority.
 * Installation, migrations and health-failure restoration need an external drill.
 */
export interface UpdateInput {
  manifest: {version:string; channel:string; sequence:number; minCompatibleVersion:string; packageSha256:string; targetSchema:number; compatibleRollbackSchemas:number[]};
  current: {version:string; channel:string; sequence:number; schema:number};
  observed: {packageSha256:string; signatureStatus:string; publisherThumbprint:string; chainValid:boolean; timestampValid:boolean; testCertificate:boolean};
  trustedPublisherThumbprints:string[];
  backup: {consistent:boolean; verified:boolean; schema:number; sha256:string};
  checkpointsSaved:boolean;
}

function version(value:string):number[] | null {
  if (!/^\d+\.\d+\.\d+$/.test(value)) return null;
  const parts=value.split('.').map(Number);
  return parts.every(Number.isSafeInteger) ? parts : null;
}
function compare(left:number[],right:number[]):number {
  for(let i=0;i<3;i++){if(left[i]!==right[i])return left[i]>right[i]?1:-1;}
  return 0;
}
export function evaluateUpdate(input:UpdateInput):{state:'REJECTED'|'READY_FOR_EXTERNAL_INSTALL';activeVersion:string;reasons:string[]} {
  const reasons:string[]=[];
  const {manifest,current,observed,backup}=input;
  const proposed=version(manifest.version),active=version(current.version),minimum=version(manifest.minCompatibleVersion);
  if(!proposed||!active||!minimum)reasons.push('VERSION_INVALID');
  if(proposed&&active&&compare(proposed,active)<=0)reasons.push('NETWORK_DOWNGRADE_OR_REPLAY');
  if(minimum&&active&&compare(active,minimum)<0)reasons.push('COMPATIBILITY_WINDOW');
  if(!Number.isSafeInteger(manifest.sequence)||manifest.sequence<=current.sequence)reasons.push('MANIFEST_REPLAY');
  if(manifest.channel!==current.channel)reasons.push('CHANNEL_MISMATCH');
  if(!/^[0-9a-f]{64}$/.test(manifest.packageSha256)||observed.packageSha256!==manifest.packageSha256)reasons.push('PACKAGE_HASH_MISMATCH');
  if(observed.signatureStatus!=='Valid'||observed.chainValid!==true||observed.timestampValid!==true||observed.testCertificate!==false)reasons.push('SIGNATURE_UNTRUSTED');
  if(!observed.publisherThumbprint||!input.trustedPublisherThumbprints.some(pin=>pin.toUpperCase()===observed.publisherThumbprint.toUpperCase()))reasons.push('PUBLISHER_UNTRUSTED');
  if(!Number.isSafeInteger(manifest.targetSchema)||manifest.targetSchema<1||!manifest.compatibleRollbackSchemas.includes(current.schema))reasons.push('SCHEMA_ROLLBACK_INCOMPATIBLE');
  if(backup.consistent!==true||backup.verified!==true||backup.schema!==current.schema||!/^[0-9a-f]{64}$/.test(backup.sha256))reasons.push('VERIFIED_BACKUP_REQUIRED');
  if(input.checkpointsSaved!==true)reasons.push('TASK_CHECKPOINTS_REQUIRED');
  return {state:reasons.length?'REJECTED':'READY_FOR_EXTERNAL_INSTALL',activeVersion:current.version,reasons};
}
