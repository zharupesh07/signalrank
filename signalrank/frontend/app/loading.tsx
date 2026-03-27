export default function Loading() {
  return (
    <div className="pt-14 min-h-screen page-content">
      <div className="max-w-4xl mx-auto px-6 py-8 flex items-center justify-center min-h-[50vh]">
        <div className="flex items-center gap-3 text-muted-foreground text-xs tracking-wider uppercase">
          <div className="w-4 h-4 border-2 border-primary border-t-transparent rounded-full spin-slow" />
          <span>Loading</span>
          <span className="cursor-blink" />
        </div>
      </div>
    </div>
  );
}
