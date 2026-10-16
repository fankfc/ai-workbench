import { describe, expect, it } from 'vitest';
import { validateCall, isTrustedSender } from '../../apps/desktop/src/shared/validation';
import { parsePublicEvent } from '../../apps/desktop/src/renderer/chat/public-events';

describe('narrow boundary', () => {
  it('allows bounded user profile fields and binds material refs to the submitted attachments',()=>{
    const input={conversationId:'cid',text:'任务',provider_profile_id:'fake-gpt',client_request_id:'rid',connection_version:'1',attachment_ids:['a1'],domain:'document',profile_inputs:{audience:'研究组',purpose:'报告',source_refs:['input/attachment_a1.md'],formats:['pdf']}};
    expect(validateCall('submitTurn',input)).toEqual(input);
    expect(()=>validateCall('submitTurn',{...input,profile_inputs:{...input.profile_inputs,source_refs:['C:/private']}})).toThrow();
    expect(()=>validateCall('submitTurn',{...input,profile_inputs:{...input.profile_inputs,source_refs:['input/attachment_foreign.md']}})).toThrow();
  });
  it('refuses renderer supplied file paths and arbitrary methods', () => {
    expect(() => validateCall('chooseFiles', { path: 'C:/secrets' })).toThrow();
    expect(() => validateCall('execute', { command: 'whoami' })).toThrow();
  });
  it('refuses wrong window and subframe senders', () => {
    const window = { webContents: { id: 5 } };
    expect(isTrustedSender({ sender: { id: 7 }, senderFrame: { url: 'file:///app/index.html' } }, window, 'file:///app/index.html')).toBe(false);
    expect(isTrustedSender({ sender: { id: 5 }, senderFrame: { url: 'https://example.com' } }, window, 'file:///app/index.html')).toBe(false);
  });
  it('drops internal events and public payloads with additional secrets', () => {
    expect(parsePublicEvent({kind:'model.delta',payload:{text:'CANARY_INTERNAL'}})).toBeNull();
    expect(parsePublicEvent({schema_version:'1.0',event_id:'e',conversation_id:'c',turn_id:'t',task_id:'k',attempt_id:'a',sequence:1,kind:'response.pending',payload:{status:'pending',token:'SECRET'}})).toBeNull();
  });
  it('accepts native English clarification without allowing arbitrary languages or English internal errors',()=>{const event={schema_version:'1.0',event_id:'e',conversation_id:'c',turn_id:'t',task_id:'k',attempt_id:'a',sequence:1,kind:'input.required',payload:{prompt_id:'p',text:'What evidence should be used?',language:'en'}};expect(parsePublicEvent(event)).not.toBeNull();expect(parsePublicEvent({...event,payload:{...event.payload,language:'fr'}})).toBeNull();expect(parsePublicEvent({...event,kind:'request.failed',payload:{error_code:'FAILED',text:'Raw internal error',language:'en',action:'none'}})).toBeNull();});
});
