/**
 * 修复 LLM 输出的非标准 Markdown 表格（缺少分隔符行）。
 *
 * DeepSeek 等模型经常省略表格的 | --- | 分隔符行，导致
 * react-markdown 无法正确渲染为 HTML 表格。此函数在渲染前
 * 自动检测并补全缺失的分隔符行。
 */

export function fixMarkdownTable(text: string): string {
  // 匹配表头行（|...|）后直接跟数据行（|...|），中间缺少分隔符行
  const regex = /^(\|.*\|)\s*\n(?!\s*\|[\s\-:]+\|)(\|.*\|)/gm;
  return text.replace(regex, (_match, headerRow: string, dataRow: string) => {
    const columns = headerRow.split("|").filter((col) => col.trim() !== "");
    const separatorRow = "| " + Array(columns.length).fill("---").join(" | ") + " |";
    return headerRow + "\n" + separatorRow + "\n" + dataRow;
  });
}
