import { build } from 'esbuild';
const testBuild=process.argv.includes('--test');const output=testBuild?'dist-test':'dist';
await build({entryPoints:['src/main/index.ts'],bundle:true,platform:'node',format:'cjs',minifySyntax:true,outfile:`${output}/main/index.cjs`,external:['electron'],define:{__TEST_BUILD__:testBuild?'true':'false'}});
await build({entryPoints:['src/preload/index.ts'],bundle:true,platform:'node',format:'cjs',outfile:`${output}/preload/index.cjs`,external:['electron']});
