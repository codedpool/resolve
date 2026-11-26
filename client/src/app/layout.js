import { Suspense } from "react";

import { SiteNav } from "@/components/SiteNav";
import { StepUpDialog } from "@/components/StepUpDialog";
import "./globals.css";

export const metadata = {
  title: "Resolve",
  description: "A case file for a consumer refund.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <div className="spine">
          <Suspense fallback={null}>
            <SiteNav />
          </Suspense>
          <Suspense fallback={<p>Loading.</p>}>{children}</Suspense>
        </div>
        <StepUpDialog />
      </body>
    </html>
  );
}
