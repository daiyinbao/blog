{{- /* 导出用的原始 Markdown：直接读取源文件，保证和原文完全一致 */ -}}
{{- $source := "" -}}
{{- with .File -}}
  {{- $source = os.ReadFile (path.Join "content" .Path) -}}
{{- end -}}
{{- if $source }}{{ $source }}{{ else }}{{ $.RawContent }}{{ end -}}
