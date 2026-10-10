import * as TabsPrimitive from "@radix-ui/react-tabs";
import type { ReactNode } from "react";

export function Tabs({
  value,
  onValueChange,
  items,
}: {
  value: string;
  onValueChange: (value: string) => void;
  items: { value: string; label: string; content: ReactNode }[];
}) {
  return (
    <TabsPrimitive.Root className="tabs-root" value={value} onValueChange={onValueChange}>
      <TabsPrimitive.List className="tabs-list">
        {items.map((item) => (
          <TabsPrimitive.Trigger key={item.value} className="tabs-trigger" value={item.value}>
            {item.label}
          </TabsPrimitive.Trigger>
        ))}
      </TabsPrimitive.List>
      {items.map((item) => (
        <TabsPrimitive.Content
          key={item.value}
          value={item.value}
          forceMount
          hidden={value !== item.value}
        >
          {item.content}
        </TabsPrimitive.Content>
      ))}
    </TabsPrimitive.Root>
  );
}
