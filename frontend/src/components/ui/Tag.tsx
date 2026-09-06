export function Tag({ children, tone = 'default' }: { children: React.ReactNode; tone?: 'default'|'red'|'green'|'blue'|'ai' }) {
  return <span className={`tag ${tone === 'default' ? '' : tone}`}>{children}</span>;
}
