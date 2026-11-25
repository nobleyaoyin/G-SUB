// Shared disclosure; callers retain their role-authorized metrics and layout.
export default function CollapsibleStatistics({className, children}) {
  return <details className={className}><summary>Statistics</summary>{children}</details>;
}
