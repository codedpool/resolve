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
        <div className="spine">{children}</div>
        <StepUpDialog />
      </body>
    </html>
  );
}
