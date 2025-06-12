'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

export default function Home() {
  const router = useRouter();

  useEffect(() => {
    // redirect to lobby page
    router.replace('/lobby');
  }, [router]);

  // show loading state, although the redirect is fast
  return (
    <div style={{
      display: 'flex',
      justifyContent: 'center',
      alignItems: 'center',
      minHeight: '100vh',
      backgroundColor: '#000000',
      color: '#00FF00',
      fontFamily: "'Quantico', sans-serif",
      fontSize: '18px'
    }}>
      Loading lobby...
    </div>
  );
}
