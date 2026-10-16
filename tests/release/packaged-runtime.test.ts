import { expect, it } from 'vitest';
import { runtimeResources } from '../../apps/desktop/src/main/backend';
import { join } from 'node:path';

it('starts packaged Python from resources without development venv paths',()=>{
  expect(runtimeResources('development',true,'C:/Program Files/AI 工作台/resources')).toEqual({root:'C:/Program Files/AI 工作台/resources',python:join('C:/Program Files/AI 工作台/resources','python','python.exe')});
  expect(runtimeResources('development',false,'ignored')).toEqual({root:'development'});
});
