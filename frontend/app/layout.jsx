import './globals.css'

export const metadata = {
  title: 'Monopoly Game AI',
  description: 'View AI Monopoly Games',
}

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
} 