import type { Attachment,ProfileInputs } from '../../shared/desktop-bridge';
import type { Draft } from './drafts';
export type TaskDetails={audience:string;purpose:string;researchQuestion:string;requirements:string;testCommand:string;workspaceId:string;evidenceIds:string[];dataIds:string[];formats:('pdf'|'docx'|'markdown')[]};
export function blankTaskDetails():TaskDetails{return {audience:'',purpose:'',researchQuestion:'',requirements:'',testCommand:'',workspaceId:'',evidenceIds:[],dataIds:[],formats:[]};}
export function attachmentRef(file:Attachment){return `input/attachment_${file.id}.${file.name.split('.').at(-1)?.toLowerCase()}`;}
export function profileInputs(draft:Draft):ProfileInputs|undefined {
  const details=draft.details;const ready=draft.attachments.filter(file=>file.status==='ready');const refs=(ids:string[])=>ready.filter(file=>ids.includes(file.id)).map(attachmentRef);
  const formats=details.formats.length?{formats:[...details.formats]}:{};
  if(draft.domain==='document')return {...(details.audience.trim()?{audience:details.audience.trim()}:{}),...(details.purpose.trim()?{purpose:details.purpose.trim()}:{}),source_refs:ready.length?ready.map(attachmentRef):['input/user_request.txt'],...formats};
  if(draft.domain==='paper')return {...(details.researchQuestion.trim()?{research_question:details.researchQuestion.trim()}:{}),evidence_refs:refs(details.evidenceIds),data_refs:refs(details.dataIds),...formats};
  if(draft.domain==='code'){const workspace=ready.find(file=>file.id===details.workspaceId);return {...(details.requirements.trim()?{requirements:details.requirements.trim()}:{}),...(details.testCommand.trim()?{test_command:details.testCommand.trim()}:{}),...(workspace?{workspace_ref:attachmentRef(workspace)}:{})};}
  const csv=ready.filter(file=>file.name.toLowerCase().endsWith('.csv'));return csv.length?{data_refs:csv.map(attachmentRef),...formats}:undefined;
}
