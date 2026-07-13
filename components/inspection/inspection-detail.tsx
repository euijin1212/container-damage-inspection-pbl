'use client'

import { useState } from 'react'
import {
  Check,
  Download,
  FileText,
  Loader2,
  MapPin,
  RefreshCw,
  ScanText,
  User,
  X,
} from 'lucide-react'
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { Progress } from '@/components/ui/progress'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { cn } from '@/lib/utils'
import type { Inspection } from '@/lib/inspection-types'
import { AnnotatedImage } from './annotated-image'
import { RiskBadge, riskScoreColor, StatusBadge } from './status-badges'
import { formatCaptured } from '@/lib/format'

interface InspectionDetailProps {
  inspection: Inspection | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onApprove: (id: string) => void
  onReject: (id: string) => void
  onReinspect: (id: string) => void
  onGenerateReport: (id: string) => void
}

const severityDot: Record<string, string> = {
  HIGH: 'bg-destructive',
  MEDIUM: 'bg-warning',
  LOW: 'bg-success',
}

export function InspectionDetail({
  inspection,
  open,
  onOpenChange,
  onApprove,
  onReject,
  onReinspect,
  onGenerateReport,
}: InspectionDetailProps) {
  const [activeDetection, setActiveDetection] = useState<string | null>(null)

  if (!inspection) return null

  const { reportStatus } = inspection

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full gap-0 p-0 sm:!max-w-2xl">
        <SheetHeader className="border-b border-border p-4">
          <div className="flex items-center gap-2">
            <span className="font-mono text-xs text-muted-foreground">{inspection.id}</span>
            <StatusBadge status={inspection.status} />
          </div>
          <SheetTitle className="font-mono text-lg tracking-tight">{inspection.containerId}</SheetTitle>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-1">
              <MapPin className="size-3.5" aria-hidden /> {inspection.lane}
            </span>
            <span className="inline-flex items-center gap-1">
              <User className="size-3.5" aria-hidden /> {inspection.inspector}
            </span>
            <span>{formatCaptured(inspection.capturedAt)}</span>
          </div>
        </SheetHeader>

        <ScrollArea className="min-h-0 flex-1">
          <div className="space-y-6 p-4">
            {/* Risk banner */}
            <div className="flex items-center justify-between rounded-lg border border-border bg-card p-4">
              <div>
                <p className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">Risk Score</p>
                <div className="mt-1 flex items-center gap-3">
                  <span className={cn('text-4xl font-semibold tabular-nums', riskScoreColor(inspection.riskScore))}>
                    {inspection.riskScore}
                  </span>
                  <RiskBadge level={inspection.riskLevel} />
                </div>
              </div>
              <div className="w-32 text-right">
                <p className="text-xs text-muted-foreground">{inspection.detectedDamage}</p>
              </div>
            </div>

            {/* Images */}
            <Tabs defaultValue="annotated">
              <div className="flex items-center justify-between">
                <h3 className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
                  Container Imagery
                </h3>
                <TabsList>
                  <TabsTrigger value="annotated">Annotated</TabsTrigger>
                  <TabsTrigger value="original">Original</TabsTrigger>
                </TabsList>
              </div>
              <TabsContent value="annotated" className="mt-3">
                <AnnotatedImage
                  src={inspection.originalImage}
                  alt={`Annotated inspection of ${inspection.containerId}`}
                  detections={inspection.detections}
                  activeId={activeDetection}
                />
              </TabsContent>
              <TabsContent value="original" className="mt-3">
                <AnnotatedImage
                  src={inspection.originalImage}
                  alt={`Original capture of ${inspection.containerId}`}
                  annotated={false}
                />
              </TabsContent>
            </Tabs>

            {/* AI detections */}
            <div>
              <h3 className="mb-2 font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
                AI Detections ({inspection.detections.length})
              </h3>
              <div className="space-y-2">
                {inspection.detections.length === 0 && (
                  <p className="rounded-md border border-border bg-card p-3 text-sm text-muted-foreground">
                    No damage detections returned by the model.
                  </p>
                )}
                {inspection.detections.map((d) => (
                  <button
                    key={d.id}
                    type="button"
                    onMouseEnter={() => setActiveDetection(d.id)}
                    onMouseLeave={() => setActiveDetection(null)}
                    onFocus={() => setActiveDetection(d.id)}
                    onBlur={() => setActiveDetection(null)}
                    className="flex w-full items-center justify-between rounded-md border border-border bg-card p-3 text-left transition-colors hover:border-primary/40"
                  >
                    <div className="flex items-center gap-2.5">
                      <span className={cn('size-2 rounded-full', severityDot[d.severity])} aria-hidden />
                      <div>
                        <p className="text-sm font-medium">{d.label}</p>
                        <p className="font-mono text-[11px] text-muted-foreground">
                          bbox [{d.box.x}, {d.box.y}, {d.box.width}, {d.box.height}]
                        </p>
                      </div>
                    </div>
                    <div className="text-right">
                      <p className="font-mono text-sm tabular-nums">{Math.round(d.confidence * 100)}%</p>
                      <p className="text-[11px] uppercase text-muted-foreground">{d.severity}</p>
                    </div>
                  </button>
                ))}
              </div>
            </div>

            {/* OCR */}
            <div>
              <h3 className="mb-2 font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
                OCR Result
              </h3>
              <div className="rounded-md border border-border bg-card p-3">
                <div className="flex items-center justify-between">
                  <span className="inline-flex items-center gap-2 font-mono text-sm">
                    <ScanText className="size-4 text-accent" aria-hidden />
                    {inspection.ocr.text}
                  </span>
                  <span className="font-mono text-xs text-muted-foreground">
                    {Math.round(inspection.ocr.confidence * 100)}% conf.
                  </span>
                </div>
                <Separator className="my-2.5" />
                <span
                  className={cn(
                    'inline-flex items-center gap-1.5 text-xs',
                    inspection.ocr.matchesManifest ? 'text-success' : 'text-warning',
                  )}
                >
                  {inspection.ocr.matchesManifest ? (
                    <>
                      <Check className="size-3.5" aria-hidden /> Matches gate manifest
                    </>
                  ) : (
                    <>
                      <X className="size-3.5" aria-hidden /> Manifest mismatch — verify manually
                    </>
                  )}
                </span>
              </div>
            </div>

            {/* Report section */}
            <div>
              <h3 className="mb-2 font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
                Damage Report
              </h3>
              <div className="rounded-md border border-border bg-card p-4">
                {reportStatus === 'NOT_STARTED' && (
                  <div className="flex items-center justify-between gap-4">
                    <div className="flex items-center gap-2.5">
                      <FileText className="size-5 text-muted-foreground" aria-hidden />
                      <div>
                        <p className="text-sm font-medium">No report generated</p>
                        <p className="text-xs text-muted-foreground">Create a PDF damage report for this container.</p>
                      </div>
                    </div>
                    <Button size="sm" onClick={() => onGenerateReport(inspection.id)}>
                      <FileText className="size-4" /> Generate
                    </Button>
                  </div>
                )}
                {reportStatus === 'GENERATING' && (
                  <div className="space-y-3">
                    <div className="flex items-center gap-2.5">
                      <Loader2 className="size-5 animate-spin text-info" aria-hidden />
                      <div>
                        <p className="text-sm font-medium">Generating report…</p>
                        <p className="text-xs text-muted-foreground">Compiling detections, imagery and OCR.</p>
                      </div>
                    </div>
                    <Progress value={62} />
                  </div>
                )}
                {reportStatus === 'READY' && (
                  <div className="flex items-center justify-between gap-4">
                    <div className="flex items-center gap-2.5">
                      <FileCheckIcon />
                      <div>
                        <p className="text-sm font-medium">Report ready</p>
                        <p className="font-mono text-xs text-muted-foreground">
                          {inspection.id}_{inspection.containerId.replace(/\s/g, '')}.pdf
                        </p>
                      </div>
                    </div>
                    <Button size="sm" variant="secondary">
                      <Download className="size-4" /> Download
                    </Button>
                  </div>
                )}
              </div>
            </div>
          </div>
        </ScrollArea>

        {/* Action footer */}
        <div className="grid grid-cols-3 gap-2 border-t border-border p-4">
          <Button variant="secondary" onClick={() => onReinspect(inspection.id)}>
            <RefreshCw className="size-4" /> Reinspect
          </Button>
          <Button
            variant="outline"
            className="border-destructive/40 text-destructive hover:bg-destructive/10"
            onClick={() => onReject(inspection.id)}
          >
            <X className="size-4" /> Reject
          </Button>
          <Button
            className="bg-success text-success-foreground hover:bg-success/90"
            onClick={() => onApprove(inspection.id)}
          >
            <Check className="size-4" /> Approve
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  )
}

function FileCheckIcon() {
  return (
    <span className="flex size-5 items-center justify-center rounded-sm bg-success/20 text-success">
      <Check className="size-3.5" aria-hidden />
    </span>
  )
}
