"""Token mappings for explicit provider wire shapes; amounts are not prices."""

def _count(value):
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise ValueError('INVALID_TOKEN_COUNT')
    return value

def normalize_usage(provider,raw,source='reported'):
    if not isinstance(raw,dict) or source not in ('reported','estimated','unknown'):
        raise ValueError('INVALID_USAGE_SOURCE')
    if provider not in ('claude','gpt','glm') or source=='unknown':
        return {'total_tokens':None,'source':'unknown','components':{},'mapping_version':'1.0'}
    inputs=_count(raw.get('input_tokens',raw.get('prompt_tokens')))
    outputs=_count(raw.get('output_tokens',raw.get('completion_tokens')))
    total=_count(raw.get('total_tokens'))
    components={'input_tokens':inputs,'output_tokens':outputs}
    anthropic = provider == 'claude' or (provider == 'glm' and raw.get('wire_protocol') == 'anthropic')
    if provider == 'glm' and raw.get('wire_protocol') not in (None, 'anthropic', 'openai'):
        raise ValueError('UNRECOGNIZED_USAGE_WIRE_PROTOCOL')
    if anthropic:
        read=_count(raw.get('cache_read_input_tokens'))
        create=_count(raw.get('cache_creation_input_tokens'))
        components.update(cache_read_input_tokens=read,cache_creation_input_tokens=create)
        if total is None and all(v is not None for v in (inputs,outputs,read,create)):
            total=inputs+outputs+read+create
    else:
        for outer,inner,label in [('input_tokens_details','cached_tokens','cached_tokens'),('output_tokens_details','reasoning_tokens','reasoning_tokens')]:
            details=raw.get(outer,{})
            if not isinstance(details,dict):
                raise ValueError('INVALID_USAGE_DETAILS')
            value=_count(details.get(inner))
            components[label]=value
            parent=inputs if label=='cached_tokens' else outputs
            if value is not None and parent is not None and value>parent:
                raise ValueError('USAGE_SUBSET_EXCEEDS_PARENT')
        if total is None and inputs is not None and outputs is not None:
            total=inputs+outputs
    if total is not None and inputs is not None and outputs is not None:
        minimum=inputs+outputs
        if anthropic:
            minimum+=sum(components[k] or 0 for k in ('cache_read_input_tokens','cache_creation_input_tokens'))
        if total<minimum:
            raise ValueError('TOTAL_SMALLER_THAN_COMPONENTS')
    return {'total_tokens':total,'source':source if total is not None else 'unknown','components':components,
        'mapping_version':'1.1' if provider == 'glm' and anthropic else '1.0'}
