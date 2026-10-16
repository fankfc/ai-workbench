export function localDayBoundary(date:string,end=false):string {
  const [year,month,day]=date.split('-').map(Number);const midnight=new Date(year,month-1,day+(end?1:0));
  return new Date(midnight.getTime()-(end?1:0)).toISOString();
}
