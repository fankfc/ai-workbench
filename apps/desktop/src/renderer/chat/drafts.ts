import type { Attachment } from '../../shared/desktop-bridge';
import { blankTaskDetails,type TaskDetails } from './profile-inputs';
export type Draft={text:string;connectionId:string;domain:string;attachments:Attachment[];details:TaskDetails;requestId:string|null;submittedText?:string};
export function blankDraft():Draft {return {text:'',connectionId:'',domain:'mixed',attachments:[],details:blankTaskDetails(),requestId:null};}
export function loadDraft(conversation:string):Draft {try{const value=JSON.parse(localStorage.getItem('draft:'+conversation)??'null');return value&&typeof value.text==='string'?{...blankDraft(),...value,details:{...blankTaskDetails(),...value.details}}:blankDraft();}catch{return blankDraft();}}
export function saveDraft(conversation:string,draft:Draft) {localStorage.setItem('draft:'+conversation,JSON.stringify(draft));}
export function migrateDraft(from:string,to:string) {const draft=loadDraft(from);saveDraft(to,draft);return draft;}
