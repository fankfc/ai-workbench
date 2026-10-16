import type { ButtonHTMLAttributes } from 'react';
export default function Button({busy,children,...props}:ButtonHTMLAttributes<HTMLButtonElement>&{busy?:boolean}) {return <button {...props} aria-busy={busy||undefined} disabled={props.disabled||busy}>{children}</button>;}
