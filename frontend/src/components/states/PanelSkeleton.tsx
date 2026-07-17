type PanelSkeletonProps = {
  rows?: number;
  compact?: boolean;
};

export default function PanelSkeleton({ rows = 3, compact = false }: PanelSkeletonProps) {
  return (
    <div
      className="flex flex-col gap-3 @md:gap-4"
      aria-busy="true"
      aria-label="Loading content"
    >
      <div className={`cc-skeleton ${compact ? "h-4 w-1/3" : "h-5 w-2/5"}`} />
      {Array.from({ length: rows }).map((_, index) => (
        <div
          key={index}
          className={`cc-skeleton ${compact ? "h-10" : "h-14"} w-full`}
          style={{ opacity: 1 - index * 0.12 }}
        />
      ))}
    </div>
  );
}