import { QueryClient } from '@tanstack/react-query';

let sse: EventSource | null = null;

const playChime = () => {
  try {
    const ctx = new (window.AudioContext || (window as any).webkitAudioContext)();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);

    osc.type = 'sine';
    osc.frequency.setValueAtTime(880, ctx.currentTime);
    osc.frequency.exponentialRampToValueAtTime(1320, ctx.currentTime + 0.1);
    
    gain.gain.setValueAtTime(0.2, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.8);

    osc.start();
    osc.stop(ctx.currentTime + 0.8);
  } catch (e) {
    console.warn('Audio Context failed', e);
  }
};

export function connectSSE(queryClient: QueryClient) {
  if (sse || typeof EventSource === 'undefined') return;

  try {
    sse = new EventSource('/jobengine/api/v1/events/stream');
    
    sse.onmessage = (event) => {
      // Invalidate active pipelines and jobs
      queryClient.invalidateQueries({ queryKey: ['/jobengine/api/v1/jobs'] });
      queryClient.invalidateQueries({ queryKey: ['/api/status'] });
      queryClient.invalidateQueries({ queryKey: ['/api/pipelines/executions'] });
      queryClient.invalidateQueries({ queryKey: ['/api/render/status'] });
      
      // Local event dispatching if components want to listen to specific job progress
      let data: any = {};
      try {
        data = JSON.parse(event.data || '{}');
      } catch (e) {}

      // Play audio chime on job completion or new approval
      if (data.type === 'job.finished' || data.type === 'approval.created') {
        playChime();
      }

      window.dispatchEvent(new CustomEvent('omni:job-event', { detail: data }));
    };

    sse.onerror = () => {
      try {
        sse?.close();
      } catch (e) {}
      sse = null;
      // Reconnect in 5 seconds on connection failures
      setTimeout(() => connectSSE(queryClient), 5000);
    };
  } catch (e) {
    sse = null;
  }
}
