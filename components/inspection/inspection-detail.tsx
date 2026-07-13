'use client'

import { useEffect, useState } from 'react'
import {
  Check,
  Download,
  FileSearch,
  FileText,
  MapPin,
  PauseCircle,
  RefreshCw,
  RotateCw,
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { Progress } from '@/components/ui/progress'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'
import type { Inspection } from '@/lib/inspection-types'
import { SEVERITY_LABEL } from '@/lib/mock-inspections'
import { AnnotatedImage } from './annotated-image'
import { ReportBadge, RiskBadge, riskScoreColor, StatusBadge } from './status-badges'
import { formatCaptured, formatDateTime } from '@/lib/format'

type ConfirmType = 'approve' | 'reject' | 'reinspect' | null

interface InspectionDetailProps {
  inspection: Inspection | null
  open: boolean
  onOpenChange: (open: boolean) => void
  queueIndex: number
  queueTotal: number
  onApprove: (id: string) => void
  onReject: (id: string, comment: string) => void
  onReinspect: (id: string, comment: string) => void
  onGenerateReport: (id: string) => void
  onHoldNext: () => void
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
  queueIndex,
  queueTotal,
  onApprove,
  onReject,
  onReinspect,
  onGenerateReport,
  onHoldNext,
}: InspectionDetailProps) {
  const [activeDetection, setActiveDetection] = useState<string | null>(null)
  const [confirm, setConfirm] = useState<ConfirmType>(null)
  const [comment, setComment] = useState('')
  const [previewOpen, setPreviewOpen] = useState(false)
  const [downloadNote, setDownloadNote] = useState(false)

  // Reset transient UI whenever the inspection changes.
  useEffect(() => {
    setActiveDetection(null)
    setConfirm(null)
    setComment('')
    setPreviewOpen(false)
    setDownloadNote(false)
  }, [inspection?.id])

  useEffect(() => {
    if (!downloadNote) return
    const t = setTimeout(() => setDownloadNote(false), 2500)
    return () => clearTimeout(t)
  }, [downloadNote])

  if (!inspection) return null

  const { reportStatus } = inspection

  function closeConfirm() {
    setConfirm(null)
    setComment('')
  }

  function runConfirm() {
    if (!inspection) return
    if (confirm === 'approve') onApprove(inspection.id)
    if (confirm === 'reject') onReject(inspection.id, comment)
    if (confirm === 'reinspect') onReinspect(inspection.id, comment)
    closeConfirm()
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="flex w-full flex-col gap-0 p-0 sm:!max-w-2xl">
        <SheetHeader className="border-b border-border p-4">
          <div className="flex items-center gap-2">
            <span className="font-mono text-xs text-muted-foreground">{inspection.id}</span>
            <StatusBadge status={inspection.status} />
            <span className="ml-auto rounded-md border border-border bg-muted px-2 py-0.5 font-mono text-[11px] text-muted-foreground">
              대기열 {queueIndex} / {queueTotal}
            </span>
          </div>
          <SheetTitle className="font-mono text-lg tracking-tight">{inspection.containerId}</SheetTitle>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-1">
              <MapPin className="size-3.5" aria-hidden /> {inspection.gate} · {inspection.lane}
            </span>
            <span className="inline-flex items-center gap-1">
              <User className="size-3.5" aria-hidden /> {inspection.inspector}
            </span>
            <span>{formatCaptured(inspection.capturedAt)}</span>
          </div>
        </SheetHeader>

        <ScrollArea className="min-h-0 flex-1">
          <div className="space-y-6 p-4">
            {/* Risk + primary damage */}
            <div className="flex items-stretch gap-3">
              <div className="flex-1 rounded-lg border border-border bg-card p-4">
                <p className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">위험 점수</p>
                <div className="mt-1 flex items-center gap-3">
                  <span className={cn('text-4xl font-semibold tabular-nums', riskScoreColor(inspection.riskScore))}>
                    {inspection.riskScore}
                  </span>
                  <RiskBadge level={inspection.riskLevel} />
                </div>
              </div>
              <div className="flex-1 rounded-lg border border-border bg-card p-4">
                <p className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">주요 감지 손상</p>
                <p className="mt-2 text-sm text-foreground text-pretty">{inspection.detectedDamage}</p>
              </div>
            </div>

            {/* Images */}
            <Tabs defaultValue="annotated">
              <div className="flex items-center justify-between">
                <h3 className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">컨테이너 이미지</h3>
                <TabsList>
                  <TabsTrigger value="annotated">AI 분석 이미지</TabsTrigger>
                  <TabsTrigger value="original">원본 이미지</TabsTrigger>
                </TabsList>
              </div>
              <TabsContent value="annotated" className="mt-3">
                <AnnotatedImage
                  src={inspection.originalImage}
                  alt={`${inspection.containerId} AI 분석 이미지`}
                  detections={inspection.detections}
                  activeId={activeDetection}
                />
              </TabsContent>
              <TabsContent value="original" className="mt-3">
                <AnnotatedImage
                  src={inspection.originalImage}
                  alt={`${inspection.containerId} 원본 이미지`}
                  annotated={false}
                />
              </TabsContent>
            </Tabs>

            {/* AI detections */}
            <div>
              <h3 className="mb-2 font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
                AI 감지 결과 ({inspection.detections.length})
              </h3>
              <div className="space-y-2">
                {inspection.detections.length === 0 && (
                  <p className="rounded-md border border-border bg-card p-3 text-sm text-muted-foreground">
                    모델이 감지한 손상이 없습니다.
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
                    className="w-full rounded-md border border-border bg-card p-3 text-left transition-colors hover:border-primary/40"
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2.5">
                        <span className={cn('size-2 rounded-full', severityDot[d.severity])} aria-hidden />
                        <p className="text-sm font-medium">{d.label}</p>
                      </div>
                      <div className="flex items-center gap-3 text-right">
                        <span className="font-mono text-sm tabular-nums">신뢰도 {Math.round(d.confidence * 100)}%</span>
                        <span className="rounded-sm border border-border px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground">
                          심각도 {SEVERITY_LABEL[d.severity]}
                        </span>
                      </div>
                    </div>
                    <p className="mt-1.5 pl-[18px] text-xs text-muted-foreground text-pretty">{d.description}</p>
                  </button>
                ))}
              </div>
            </div>

            {/* OCR */}
            <div>
              <h3 className="mb-2 font-mono text-[11px] uppercase tracking-wider text-muted-foreground">OCR 결과</h3>
              <div className="rounded-md border border-border bg-card p-3">
                <div className="flex items-center justify-between">
                  <span className="inline-flex items-center gap-2 font-mono text-sm">
                    <ScanText className="size-4 text-accent" aria-hidden />
                    {inspection.ocr.text || '인식 실패'}
                  </span>
                  <span className="font-mono text-xs text-muted-foreground">
                    신뢰도 {Math.round(inspection.ocr.confidence * 100)}%
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
                      <Check className="size-3.5" aria-hidden /> 게이트 매니페스트와 일치
                    </>
                  ) : (
                    <>
                      <X className="size-3.5" aria-hidden /> 매니페스트 불일치 — 수동 확인 필요
                    </>
                  )}
                </span>
              </div>
            </div>

            {/* Capture info */}
            <div>
              <h3 className="mb-2 font-mono text-[11px] uppercase tracking-wider text-muted-foreground">촬영 정보</h3>
              <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-border bg-border">
                <InfoCell label="게이트 및 레인" value={`${inspection.gate} · ${inspection.lane}`} />
                <InfoCell label="담당 검수자" value={inspection.inspector} />
                <InfoCell label="촬영 시간" value={formatDateTime(inspection.capturedAt)} />
                <InfoCell label="검수 ID" value={inspection.id} mono />
              </dl>
            </div>

            {/* Report section */}
            <div>
              <h3 className="mb-2 font-mono text-[11px] uppercase tracking-wider text-muted-foreground">보고서 상태</h3>
              <div className="space-y-3 rounded-md border border-border bg-card p-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2.5">
                    <FileText className="size-5 text-muted-foreground" aria-hidden />
                    <div>
                      <ReportBadge status={reportStatus} />
                      <p className="mt-1 font-mono text-xs text-muted-foreground">
                        {reportStatus === 'CREATED' && inspection.reportCreatedAt
                          ? `생성 일시 ${formatDateTime(inspection.reportCreatedAt)}`
                          : reportStatus === 'GENERATING'
                            ? '검출 결과 · 이미지 · OCR 취합 중'
                            : reportStatus === 'FAILED'
                              ? '보고서 생성에 실패했습니다.'
                              : '아직 생성된 보고서가 없습니다.'}
                      </p>
                    </div>
                  </div>
                  {reportStatus === 'PENDING' && (
                    <Button size="sm" onClick={() => onGenerateReport(inspection.id)}>
                      <FileText className="size-4" /> 보고서 생성
                    </Button>
                  )}
                  {reportStatus === 'FAILED' && (
                    <Button size="sm" variant="secondary" onClick={() => onGenerateReport(inspection.id)}>
                      <RotateCw className="size-4" /> 재생성
                    </Button>
                  )}
                </div>

                {reportStatus === 'GENERATING' && <Progress value={62} />}

                {reportStatus === 'CREATED' && (
                  <>
                    <Separator />
                    <div className="flex flex-wrap items-center gap-2">
                      <Button size="sm" variant="secondary" onClick={() => setPreviewOpen(true)}>
                        <FileSearch className="size-4" /> 보고서 미리보기
                      </Button>
                      <Button size="sm" variant="outline" onClick={() => setDownloadNote(true)}>
                        <Download className="size-4" /> PDF 다운로드
                      </Button>
                      {downloadNote && (
                        <span className="font-mono text-xs text-info">PDF 다운로드를 시작했습니다. (데모 환경)</span>
                      )}
                    </div>
                  </>
                )}

                {(reportStatus === 'PENDING' || reportStatus === 'GENERATING') && (
                  <div className="flex flex-wrap items-center gap-2 opacity-60">
                    <Button size="sm" variant="secondary" disabled>
                      <FileSearch className="size-4" /> 보고서 미리보기
                    </Button>
                    <Button size="sm" variant="outline" disabled>
                      <Download className="size-4" /> PDF 다운로드
                    </Button>
                  </div>
                )}
              </div>
            </div>
          </div>
        </ScrollArea>

        {/* Action footer */}
        <div className="grid grid-cols-2 gap-2 border-t border-border p-4 sm:grid-cols-4">
          <Button variant="secondary" onClick={() => setConfirm('reinspect')}>
            <RefreshCw className="size-4" /> 재검수 요청
          </Button>
          <Button
            variant="outline"
            className="border-destructive/40 text-destructive hover:bg-destructive/10"
            onClick={() => setConfirm('reject')}
          >
            <X className="size-4" /> 반려
          </Button>
          <Button variant="outline" onClick={onHoldNext}>
            <PauseCircle className="size-4" /> 보류하고 다음
          </Button>
          <Button className="bg-success text-success-foreground hover:bg-success/90" onClick={() => setConfirm('approve')}>
            <Check className="size-4" /> 승인
          </Button>
        </div>
      </SheetContent>

      {/* Confirm dialogs */}
      <Dialog open={confirm !== null} onOpenChange={(o) => !o && closeConfirm()}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {confirm === 'approve' && '검수 승인'}
              {confirm === 'reject' && '검수 반려'}
              {confirm === 'reinspect' && '재검수 요청'}
            </DialogTitle>
            <DialogDescription className="font-mono text-xs">
              {inspection.id} · {inspection.containerId}
            </DialogDescription>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            {confirm === 'approve' && '이 컨테이너 검수 건을 승인하시겠습니까? 승인 후 다음 검수 항목으로 이동합니다.'}
            {confirm === 'reject' && '이 컨테이너 검수 건을 반려하시겠습니까? 반려 사유를 남겨 주세요.'}
            {confirm === 'reinspect' && '이 컨테이너의 재검수를 요청하시겠습니까? 요청 사유를 남겨 주세요.'}
          </p>
          {(confirm === 'reject' || confirm === 'reinspect') && (
            <Textarea
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="검수 의견을 입력하세요 (선택)"
              rows={3}
            />
          )}
          <DialogFooter className="gap-2 sm:justify-end">
            <Button variant="outline" onClick={closeConfirm}>
              취소
            </Button>
            <Button
              onClick={runConfirm}
              className={cn(
                confirm === 'approve' && 'bg-success text-success-foreground hover:bg-success/90',
                confirm === 'reject' && 'bg-destructive text-destructive-foreground hover:bg-destructive/90',
              )}
            >
              {confirm === 'approve' && '승인'}
              {confirm === 'reject' && '반려'}
              {confirm === 'reinspect' && '재검수 요청'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Report preview dialog */}
      <Dialog open={previewOpen} onOpenChange={setPreviewOpen}>
        <DialogContent className="max-h-[85vh] gap-0 overflow-y-auto sm:!max-w-2xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <FileText className="size-5 text-info" aria-hidden /> 컨테이너 손상 보고서
            </DialogTitle>
            <DialogDescription className="font-mono text-xs">
              {inspection.id} · {inspection.reportCreatedAt ? formatDateTime(inspection.reportCreatedAt) : ''}
            </DialogDescription>
          </DialogHeader>
          <div className="mt-2 space-y-4">
            <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-border bg-border">
              <InfoCell label="컨테이너 번호" value={inspection.containerId} mono />
              <InfoCell label="검수 일시" value={formatDateTime(inspection.capturedAt)} />
              <InfoCell label="위험 점수" value={`${inspection.riskScore} / 100`} />
              <InfoCell label="위험도" value={SEVERITY_LABEL[inspection.riskLevel]} />
            </dl>
            <ReportBlock title="감지된 손상">
              <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
                {inspection.detections.length === 0 && <li>감지된 손상 없음</li>}
                {inspection.detections.map((d) => (
                  <li key={d.id}>
                    {d.label} · 신뢰도 {Math.round(d.confidence * 100)}% · 심각도 {SEVERITY_LABEL[d.severity]}
                  </li>
                ))}
              </ul>
            </ReportBlock>
            <ReportBlock title="AI 분석 요약">
              <p className="text-sm text-muted-foreground text-pretty">{inspection.aiSummary || '요약 없음'}</p>
            </ReportBlock>
            <ReportBlock title="검수자 의견">
              <p className="text-sm text-muted-foreground text-pretty">{inspection.reviewerComment || '작성된 의견 없음'}</p>
            </ReportBlock>
            <ReportBlock title="최종 판정">
              <p className="text-sm font-medium text-foreground">{inspection.verdict || '판정 없음'}</p>
            </ReportBlock>
          </div>
          <DialogFooter className="mt-4 gap-2 sm:justify-end">
            <Button variant="outline" onClick={() => setPreviewOpen(false)}>
              닫기
            </Button>
            <Button
              onClick={() => {
                setPreviewOpen(false)
                setDownloadNote(true)
              }}
            >
              <Download className="size-4" /> PDF 다운로드
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Sheet>
  )
}

function InfoCell({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="bg-card p-3">
      <dt className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">{label}</dt>
      <dd className={cn('mt-0.5 text-sm text-foreground', mono && 'font-mono')}>{value}</dd>
    </div>
  )
}

function ReportBlock({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-border bg-card p-3">
      <h4 className="mb-2 font-mono text-[11px] uppercase tracking-wider text-muted-foreground">{title}</h4>
      {children}
    </div>
  )
}
