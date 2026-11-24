import Foundation
import Vision
import Darwin

// Recognition does not correct spelling: changed product text must stay visible.
let start = ProcessInfo.processInfo.systemUptime
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.recognitionLanguages = ["en-US"]
request.usesLanguageCorrection = false
let input = FileHandle.standardInput.readDataToEndOfFile()
try VNImageRequestHandler(data: input, options: [:]).perform([request])
let observations = (request.results ?? []).sorted { $0.boundingBox.midY > $1.boundingBox.midY }
let lines: [[String: Any]] = observations.prefix(200).compactMap { observation in
    guard let text = observation.topCandidates(1).first else { return nil }
    let b = observation.boundingBox
    return ["text": String(text.string.prefix(1000)), "confidence": text.confidence,
            "box": [b.minX, b.minY, b.width, b.height]]
}
var usage = rusage()
getrusage(RUSAGE_SELF, &usage)
let result: [String: Any] = ["lines": lines, "seconds": ProcessInfo.processInfo.systemUptime-start,
    "peak_rss_bytes": usage.ru_maxrss, "request_revision": request.revision,
    "recognition_level": "accurate", "language_correction": false,
    "truncated": observations.count > 200 || observations.contains { ($0.topCandidates(1).first?.string.count ?? 0) > 1000 },
    "coordinates": "normalized bottom-left origin"]
let data = try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
print(String(data: data, encoding: .utf8)!)
