export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`skeleton rounded-sm ${className}`} />;
}

export function JobCardSkeleton() {
  return (
    <div className="border border-[#3f3f46] bg-[#18181b] p-4 space-y-2">
      <div className="flex items-start justify-between">
        <div className="space-y-1.5 flex-1">
          <Skeleton className="h-3 w-48" />
          <Skeleton className="h-2.5 w-32" />
        </div>
        <Skeleton className="h-5 w-10 ml-4" />
      </div>
      <div className="flex gap-2">
        <Skeleton className="h-2 w-12" />
        <Skeleton className="h-2 w-16" />
      </div>
    </div>
  );
}

export function TableRowSkeleton({ cols = 7 }: { cols?: number }) {
  return (
    <tr className="border-b border-[#3f3f46]">
      {Array.from({ length: cols }).map((_, i) => (
        <td key={i} className="px-3 py-3">
          <Skeleton className={`h-2.5 ${i === 0 ? "w-36" : i === 1 ? "w-24" : "w-16"}`} />
        </td>
      ))}
    </tr>
  );
}

export function StatCardSkeleton() {
  return (
    <div className="border border-[#3f3f46] bg-[#18181b] p-4 space-y-2">
      <Skeleton className="h-2 w-20" />
      <Skeleton className="h-6 w-16" />
    </div>
  );
}

export function ChartSkeleton({ rows = 5 }: { rows?: number }) {
  const heights = [60, 80, 45, 90, 55, 70, 40];
  return (
    <div className="flex items-end gap-2 h-32">
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          className="skeleton flex-1 rounded-sm"
          style={{ height: `${heights[i % heights.length]}%` }}
        />
      ))}
    </div>
  );
}

export function ResumePreviewSkeleton() {
  return (
    <div className="space-y-2 p-4 border border-border bg-card">
      <Skeleton className="h-3 w-3/4" />
      <Skeleton className="h-3 w-full" />
      <Skeleton className="h-3 w-5/6" />
      <Skeleton className="h-3 w-full" />
      <Skeleton className="h-3 w-2/3" />
      <div className="pt-2 space-y-2">
        <Skeleton className="h-3 w-1/2" />
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-4/5" />
      </div>
    </div>
  );
}
