import { useState } from 'react';
import { getBaseUrl, setBaseUrl } from '../api';
import { Button, Card } from '../components/ui';

interface SettingsProps {
  dark: boolean;
  onToggleDark: () => void;
}

export function Settings({ dark, onToggleDark }: SettingsProps) {
  const [url, setUrl] = useState(getBaseUrl());
  const [test, setTest] = useState<'idle' | 'testing' | 'ok' | 'fail'>('idle');
  const [testMsg, setTestMsg] = useState('');

  const save = async () => {
    setBaseUrl(url);
    setTest('testing');
    try {
      const res = await fetch(`${getBaseUrl()}/api/status`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setTest('ok');
      setTestMsg('Kết nối OK! 🎉');
    } catch (e: unknown) {
      setTest('fail');
      setTestMsg(e instanceof Error ? e.message : 'Không kết nối được');
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <Card>
        <div className="font-display font-bold" style={{ color: 'var(--heading)' }}>Server OmniCast 🖥️</div>
        <p className="mt-1 text-xs" style={{ color: 'var(--text2)' }}>
          Địa chỉ backend trong LAN, vd <span className="font-mono">http://192.168.1.10:8767</span>.
          Máy tính phải chạy <span className="font-mono">run_backend.py --host 0.0.0.0</span>.
        </p>
        <input
          value={url}
          onChange={e => setUrl(e.target.value)}
          placeholder="http://192.168.1.10:8767"
          inputMode="url"
          autoCapitalize="none"
          className="sticker-sm mt-3 w-full px-4 py-2.5 font-mono text-sm outline-none"
          style={{ background: 'var(--surface2)', color: 'var(--text)' }}
        />
        <div className="mt-3">
          <Button cta full onClick={() => void save()}>💾 Lưu & kiểm tra ✦</Button>
        </div>
        {test !== 'idle' && (
          <div className="mt-2 text-center text-sm font-semibold"
            style={{ color: test === 'ok' ? 'var(--green-ink)' : test === 'fail' ? 'var(--red)' : 'var(--text2)' }}>
            {test === 'testing' ? 'Đang kiểm tra…' : testMsg}
          </div>
        )}
      </Card>

      <Card className="flex items-center justify-between">
        <div>
          <div className="font-display font-bold" style={{ color: 'var(--heading)' }}>Giao diện</div>
          <div className="text-xs" style={{ color: 'var(--text2)' }}>
            {dark ? 'Hoàng hôn trên ao 🌇' : 'Ao cá ban ngày 🐟'}
          </div>
        </div>
        <Button tone="purple" small onClick={onToggleDark}>{dark ? '☀️ Ngày' : '🌇 Hoàng hôn'}</Button>
      </Card>

      <Card className="text-center text-xs" style={{ color: 'var(--text3)' }}>
        OmniCast Mobile v0.2 · giao diện Ao Cá 🐟🌿
      </Card>
    </div>
  );
}
