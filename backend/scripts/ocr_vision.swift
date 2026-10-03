// ocr_vision.swift — macOS Vision framework 离线 OCR 工具（中文优先）。
//
// 定位：task-screenshot-import 的 OCR 引擎。零外部依赖（macOS 系统框架），
// 无网络、无 API key。输入图片路径，输出识别文本（每行一个识别片段，stdout）。
//
// 用法：ocr_vision <image_path>
// 退出码：0 成功（可能无文本）；2 参数错误/图片无法解码；3 识别失败。
//
// 注意：外部内容按敌意输入处理——本工具只做 OCR 文本提取，不做任何指令解析；
// 指令型内容的剥离由上游 python 管线（note_import.parse_note）负责。
import Foundation
import Vision
import ImageIO

// 图片解码：支持 png/jpeg/heic 等 ImageIO 可解码格式。
func loadCGImage(_ path: String) -> CGImage? {
    let url = URL(fileURLWithPath: path)
    guard let src = CGImageSourceCreateWithURL(url as CFURL, nil),
          let cg = CGImageSourceCreateImageAtIndex(src, 0, nil) else {
        return nil
    }
    return cg
}

// OCR 识别：zh-Hans 优先 + en-US 兜底，accurate 精度。
func recognize(_ cg: CGImage) throws -> [String] {
    var lines: [String] = []
    let request = VNRecognizeTextRequest { req, _ in
        guard let obs = req.results as? [VNRecognizedTextObservation] else { return }
        // 按图片从上到下排序输出（Vision 结果已大致有序，这里显式排序保证稳定）。
        for o in obs.sorted(by: { $0.boundingBox.midY > $1.boundingBox.midY }) {
            if let top = o.topCandidates(1).first {
                let t = top.string.trimmingCharacters(in: .whitespacesAndNewlines)
                if !t.isEmpty {
                    lines.append(t)
                }
            }
        }
    }
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["zh-Hans", "en-US"]
    request.usesLanguageCorrection = true
    let handler = VNImageRequestHandler(cgImage: cg, options: [:])
    try handler.perform([request])
    return lines
}

guard CommandLine.arguments.count > 1 else {
    FileHandle.standardError.write("usage: ocr_vision <image_path>\n".data(using: .utf8)!)
    exit(2)
}

let path = CommandLine.arguments[1]
guard let cg = loadCGImage(path) else {
    FileHandle.standardError.write("cannot decode image: \(path)\n".data(using: .utf8)!)
    exit(2)
}

do {
    let lines = try recognize(cg)
    let out = lines.joined(separator: "\n") + (lines.isEmpty ? "" : "\n")
    FileHandle.standardOutput.write(out.data(using: .utf8)!)
    exit(0)
} catch {
    FileHandle.standardError.write("ocr failed: \(error)\n".data(using: .utf8)!)
    exit(3)
}