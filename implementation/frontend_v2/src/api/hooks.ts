import { useQuery, useQueryClient } from '@tanstack/react-query';
import { apiGet } from './client';

export function useApi<T>(
  path: string, 
  options: { 
    refetchInterval?: number | false | ((query: any) => number | false);
    enabled?: boolean;
  } = {}
) {
  // Determine default polling intervals
  let defaultInterval: number | false = false;
  if (path === '/api/status') {
    defaultInterval = 5000;
  } else if (path === '/api/approvals') {
    defaultInterval = 10000;
  }

  const refetchInterval = options.refetchInterval !== undefined 
    ? options.refetchInterval 
    : defaultInterval;

  return useQuery<T>({
    queryKey: [path],
    queryFn: () => apiGet<T>(path),
    refetchInterval,
    staleTime: 30000, // 30s stale time
    refetchOnWindowFocus: true,
    enabled: options.enabled,
  });
}

export function useInvalidate() {
  const queryClient = useQueryClient();
  return (path: string) => {
    queryClient.invalidateQueries({ queryKey: [path] });
  };
}
