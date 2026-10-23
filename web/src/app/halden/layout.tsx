import { SubNav } from "@/components/nav";
import { Callout } from "@/components/ui";

const SECTIONS = [
  { href: "/halden", label: "Performance" },
  { href: "/halden/changes", label: "Changes" },
  { href: "/halden/evidence", label: "Evidence" },
  { href: "/halden/decision", label: "Decision" },
];

export default function HaldenLayout({ children }: LayoutProps<"/halden">) {
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3">
        <Callout>
          <strong className="font-medium text-ink">Simulated workspace.</strong> Halden Coffee Works is fictional. Its
          causal truth was written down before any model was fit, which is what lets ATLAS grade each measurement
          method against it. 156 weeks of history, 10 regions, 6 paid channels.
        </Callout>
        <SubNav items={SECTIONS} />
      </div>
      {children}
    </div>
  );
}
