import type { Metadata } from 'next'
import { Fira_Code, Fira_Sans } from 'next/font/google'
import './globals.css'

const firaCode = Fira_Code({
  subsets: ['latin'],
  variable: '--font-fira-code',
})

const firaSans = Fira_Sans({
  subsets: ['latin'],
  weight: ['400', '500', '600'],
  variable: '--font-fira-sans',
})

export const metadata: Metadata = {
  title: 'Mercury — Weather Model vs Market',
  description: 'Forecast accuracy dashboard',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`dark ${firaCode.variable} ${firaSans.variable}`}>
      <body
        style={{
          background: 'var(--color-bg)',
          color: 'var(--color-text)',
          fontFamily: 'var(--font-fira-sans, sans-serif)',
        }}
      >
        {children}
      </body>
    </html>
  )
}
