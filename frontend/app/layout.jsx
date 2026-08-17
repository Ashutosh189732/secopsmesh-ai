import "./globals.css";

export const metadata = {
  title: "SecOpsMeshAI Dashboard",
  description: "Agentic SOC investigation pipeline — analyst dashboard",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <div className="min-h-screen">
          <header className="border-b border-gray-200 bg-white px-6 py-4">
            <h1 className="text-lg font-semibold text-gray-900">SecOpsMeshAI</h1>
            <p className="text-sm text-gray-500">Agentic SOC investigation dashboard</p>
          </header>
          <main className="mx-auto max-w-6xl px-6 py-8">{children}</main>
        </div>
      </body>
    </html>
  );
}
