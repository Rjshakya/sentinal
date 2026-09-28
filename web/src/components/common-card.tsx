
import { Card, CardContent, CardFooter, CardHeader } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type React from "react";

type CommonCardProps = {
  header?: React.ReactNode;
  body?: React.ReactNode;
  footer?: React.ReactNode;
  className?: string;
  headerClassName?: string;
  cardClassName?: string;
  bodyClassName?: string;
  footerClassName?: string;
  id?: string;
};

const CommonCard = (props: CommonCardProps) => {
  return (
    <div id={props.id} className={cn("grid gap-1 p-1 bg-accent  ring-1 ring-foreground/10", props.className)}>
      {props.header && (
        <CardHeader className={cn("flex items-center gap-2 pt-0 pb-1 px-1 ", props.headerClassName)}>
          {props.header}
        </CardHeader>
      )}
      <Card className={cn("bg-background ring-0 border-0 ", props.cardClassName)}>
        {props.body && <CardContent className={props.bodyClassName}>{props.body}</CardContent>}
        {props.footer && <CardFooter className={cn(props.footerClassName, 'bg-accent')}>{props.footer}</CardFooter>}
      </Card>
    </div>
  );
};

export { CommonCard }
