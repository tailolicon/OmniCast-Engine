import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'com.omnicast.mobile',
  appName: 'OmniCast',
  webDir: 'dist',
  server: {
    // Webview origin http://localhost — cho phép fetch tới backend http:// trong LAN
    // (androidScheme https sẽ chặn mixed-content khi gọi http://192.168.x.x:8767).
    androidScheme: 'http',
    cleartext: true,
  },
};

export default config;
