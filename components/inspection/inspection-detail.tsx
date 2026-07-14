'use client'

import { useEffect, useState } from 'react'
import {
  Check,
  Download,
  FileSearch,
  FileText,
  PauseCircle,
  RefreshCw,
  RotateCw,
  ScanText,
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

function getPrimaryConfidence(inspection: Inspection) {
  const top = inspection.detections.reduce((max, detection) => Math.max(max, detection.confidence), 0)
  return Math.round(top * 100)
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
  }, [inspection?.event_id])

  useEffect(() => {
    if (!downloadNote) return
    const t = setTimeout(() => setDownloadNote(false), 2500)
    return () => clearTimeout(t)
  }, [downloadNote])

  if (!inspection) return null

  const report_status = inspection.report?.report_status ?? inspection.report_status ?? 'PENDING'
  const report_created_at = inspection.report?.report_created_at ?? inspection.report_created_at

  function closeConfirm() {
    setConfirm(null)
    setComment('')
  }

  function runConfirm() {
    if (!inspection) return
    if (confirm === 'approve') onApprove(inspection.event_id)
    if (confirm === 'reject') onReject(inspection.event_id, comment)
    if (confirm === 'reinspect') onReinspect(inspection.event_id, comment)
    closeConfirm()
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="flex w-full flex-col gap-0 bg-slate-950 p-0 text-slate-100 sm:!max-w-2xl">
        <SheetHeader className="border-b border-white/10 bg-slate-950 p-6">
          <div className="flex items-center justify-between gap-3">
            <span className="text-sm text-slate-400">컨테이너</span>
            <span className="rounded-full bg-white/10 px-2.5 py-1 text-xs text-slate-300">
              대기열 {queueIndex} / {queueTotal}
            </span>
          </div>
          <SheetTitle className="text-3xl font-bold tracking-tight text-white">{inspection.container_id}</SheetTitle>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-slate-400">
            <span>{formatCaptured(inspection.captured_at)}</span>
            <StatusBadge status={inspection.review_status} />
          </div>
          <div className="flex items-center gap-3">
            <span className={cn('text-4xl font-bold tabular-nums leading-none', riskScoreColor(inspection.risk_score))}>
              {inspection.risk_score}
            </span>
            <RiskBadge level={inspection.risk_level} />
          </div>
        </SheetHeader>

        <ScrollArea className="min-h-0 flex-1">
          <div className="space-y-6 p-5">
            {/* Images */}
            <Tabs defaultValue="annotated">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-slate-200">AI 분석 이미지</h3>
                <TabsList className="bg-white/10 text-slate-400">
                  <TabsTrigger value="annotated" className="text-slate-300 data-active:bg-white/15 data-active:text-white">
                    AI 분석 이미지
                  </TabsTrigger>
                  <TabsTrigger value="original" className="text-slate-300 data-active:bg-white/15 data-active:text-white">
                    원본 이미지
                  </TabsTrigger>
                </TabsList>
              </div>
              <TabsContent value="annotated" className="mt-3">
                <AnnotatedImage
                  src={inspection.annotated_s3_url || inspection.raw_image_url}
                  alt={`${inspection.container_id} AI 분석 이미지`}
                  detections={inspection.detections}
                  activeId={activeDetection}
                />
              </TabsContent>
              <TabsContent value="original" className="mt-3">
                <AnnotatedImage
                  src={inspection.raw_image_url}
                  alt={`${inspection.container_id} 원본 이미지`}
                  annotated={false}
                />
              </TabsContent>
            </Tabs>

            {/* AI reading panel */}
            <div className="rounded-lg bg-slate-900">
              <div className="border-b border-white/10 px-5 py-4">
                <h3 className="text-sm font-semibold text-slate-100">AI 판독 패널</h3>
              </div>
              <div className="grid gap-px bg-white/10 md:grid-cols-2">
                <InfoCell label="감지 손상" value={inspection.damage_summary} tone="dark" />
                <InfoCell label="신뢰도" value={inspection.detections.length ? `${getPrimaryConfidence(inspection)}%` : '감지 없음'} tone="dark" />
                <InfoCell label="심각도" value={SEVERITY_LABEL[inspection.risk_level]} tone="dark" />
                <div className="bg-slate-900 p-4">
                  <dt className="text-xs text-slate-400">OCR 결과</dt>
                  <dd className="mt-1 flex flex-wrap items-center gap-2 text-sm text-slate-100">
                    <span className="inline-flex items-center gap-1.5">
                      <ScanText className="size-4 text-accent" aria-hidden />
                      {inspection.ocr.text || '인식 실패'}
                    </span>
                    <span className={cn('text-xs', inspection.ocr.matches_manifest ? 'text-success' : 'text-warning')}>
                      {inspection.ocr.matches_manifest ? 'Manifest 일치' : 'Manifest 확인 필요'}
                    </span>
                  </dd>
                </div>
              </div>
              <div className="border-t border-white/10 p-5">
                <p className="text-xs text-slate-400">AI 판단 근거</p>
                <p className="mt-2 text-sm leading-6 text-slate-300 text-pretty">
                  {inspection.ai_summary || 'AI 판독 요약이 아직 생성되지 않았습니다.'}
                </p>
              </div>
              <div className="border-t border-white/10 p-5">
                <div className="mb-2 flex items-center justify-between">
                  <h4 className="text-sm font-medium text-slate-300">
                    감지 결과 {inspection.detections.length}건
                  </h4>
                  <span className="text-xs text-slate-500">{inspection.event_id}</span>
                </div>
                <div className="space-y-2">
                {inspection.detections.length === 0 && (
                  <p className="rounded-md bg-white/5 p-3 text-sm text-slate-400">
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
                    className="w-full rounded-md bg-white/5 p-3 text-left transition-colors hover:bg-white/10"
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2.5">
                        <span className={cn('size-2 rounded-full', severityDot[d.severity])} aria-hidden />
                        <p className="text-sm font-medium text-slate-100">{d.label}</p>
                      </div>
                      <div className="flex items-center gap-3 text-right">
                        <span className="text-sm tabular-nums text-slate-300">신뢰도 {Math.round(d.confidence * 100)}%</span>
                        <span className="rounded-full bg-white/10 px-2 py-0.5 text-xs text-slate-300">
                          심각도 {SEVERITY_LABEL[d.severity]}
                        </span>
                      </div>
                    </div>
                    <p className="mt-1.5 pl-[18px] text-xs text-slate-400 text-pretty">{d.description}</p>
                  </button>
                ))}
                </div>
              </div>
            </div>

            {/* Capture info */}
            <div>
              <h3 className="mb-2 text-sm font-semibold text-slate-300">촬영 정보</h3>
              <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-lg bg-white/10">
                <InfoCell label="촬영 시간" value={formatDateTime(inspection.captured_at)} tone="dark" />
                <InfoCell label="담당 검수자" value={inspection.assigned_inspector || '미배정'} tone="dark" />
              </dl>
            </div>

            {/* Report section */}
            <div>
              <h3 className="mb-2 text-sm font-semibold text-slate-300">보고서 상태</h3>
              <div className="space-y-3 rounded-lg bg-slate-900 p-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2.5">
                    <FileText className="size-5 text-muted-foreground" aria-hidden />
                    <div>
                      <ReportBadge status={report_status} />
                      <p className="mt-1 text-xs text-slate-400">
                        {(report_status === 'GENERATED' || report_status === 'COMPLETED') && report_created_at
                          ? `생성 일시 ${formatDateTime(report_created_at)}`
                          : report_status === 'GENERATING'
                            ? '검출 결과 · 이미지 · OCR 취합 중'
                            : report_status === 'FAILED'
                              ? '보고서 생성에 실패했습니다.'
                              : '아직 생성된 보고서가 없습니다.'}
                      </p>
                    </div>
                  </div>
                  {report_status === 'PENDING' && (
                    <Button size="sm" onClick={() => onGenerateReport(inspection.event_id)}>
                      <FileText className="size-4" /> 보고서 생성
                    </Button>
                  )}
                  {report_status === 'FAILED' && (
                    <Button size="sm" variant="secondary" onClick={() => onGenerateReport(inspection.event_id)}>
                      <RotateCw className="size-4" /> 재생성
                    </Button>
                  )}
                </div>

                {report_status === 'GENERATING' && <Progress value={62} />}

                {(report_status === 'GENERATED' || report_status === 'COMPLETED') && (
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
                        <span className="text-xs text-blue-300">PDF 다운로드를 시작했습니다. (데모 환경)</span>
                      )}
                    </div>
                  </>
                )}

                {(report_status === 'PENDING' || report_status === 'GENERATING') && (
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
        <div className="grid grid-cols-2 gap-2 border-t border-white/10 bg-slate-950 p-4 sm:grid-cols-4">
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
            <DialogDescription className="text-xs">
              {inspection.event_id} · {inspection.container_id}
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
            <DialogDescription className="text-xs">
              {inspection.event_id} · {report_created_at ? formatDateTime(report_created_at) : ''}
            </DialogDescription>
          </DialogHeader>
          <div className="mt-2 space-y-4">
            <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-border bg-border">
              <InfoCell label="컨테이너 번호" value={inspection.container_id} />
              <InfoCell label="검수 일시" value={formatDateTime(inspection.captured_at)} />
              <InfoCell label="위험 점수" value={`${inspection.risk_score} / 100`} />
              <InfoCell label="위험도" value={SEVERITY_LABEL[inspection.risk_level]} />
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
              <p className="text-sm text-muted-foreground text-pretty">{inspection.ai_summary || '요약 없음'}</p>
            </ReportBlock>
            <ReportBlock title="검수자 의견">
              <p className="text-sm text-muted-foreground text-pretty">{inspection.reviewer_comment || '작성된 의견 없음'}</p>
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

function InfoCell({
  label,
  value,
  mono,
  tone = 'light',
}: {
  label: string
  value: string
  mono?: boolean
  tone?: 'light' | 'dark'
}) {
  const dark = tone === 'dark'

  return (
    <div className={cn('p-4', dark ? 'bg-slate-900' : 'bg-card')}>
      <dt className={cn('text-xs', dark ? 'text-slate-400' : 'text-muted-foreground')}>{label}</dt>
      <dd className={cn('mt-1 text-sm', dark ? 'text-slate-100' : 'text-foreground', mono && 'font-medium')}>{value}</dd>
    </div>
  )
}

function ReportBlock({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-border bg-card p-3">
      <h4 className="mb-2 text-sm font-semibold text-foreground">{title}</h4>
      {children}
    </div>
  )
}
