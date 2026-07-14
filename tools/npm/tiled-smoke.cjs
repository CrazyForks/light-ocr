'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

async function main() {
  const fixtureDirectory = path.resolve(process.argv[2] ?? '');
  if (!process.argv[2]) throw new Error('fixture directory is required');
  const metadata = JSON.parse(
    fs.readFileSync(path.join(fixtureDirectory, 'fixture.json'), 'utf8'),
  );
  const pixels = fs.readFileSync(path.join(fixtureDirectory, 'pixels.bin'));
  assert.equal(
    crypto.createHash('sha256').update(pixels).digest('hex'),
    metadata.pixelSha256,
    'fixture pixel hash mismatch',
  );
  const expected = metadata.annotations
    .slice()
    .sort((left, right) => left.order - right.order)
    .map((annotation) => annotation.text.normalize('NFKC'));

  const { createEngine } = require('@arcships/light-ocr');
  const engine = await createEngine({ detection: { strategy: 'tiled' } });
  try {
    assert.equal(engine.info.detectionStrategy, 'tiled');
    assert.equal(engine.info.tiledDetection.contractVersion, 'tiled-v1');
    const result = await engine.recognize({
      data: pixels,
      width: metadata.width,
      height: metadata.height,
      stride: metadata.stride,
      pixelFormat: metadata.pixelFormat,
    }, { includeDiagnostics: true });
    assert.deepEqual(
      result.lines.map((line) => line.text.normalize('NFKC')),
      expected,
      'tiled text or reading order mismatch',
    );
    assert.equal(result.diagnostics.detectionPasses.length, 4);
    assert.equal(result.diagnostics.maxLiveDetectionPassBuffers, 1);
    assert.ok(result.diagnostics.detectionPasses.every(
      (item) => item.tensorWidth <= 1280 && item.tensorHeight <= 1280,
    ));
    assert.equal(
      result.diagnostics.rawDetectionBoxes
        - result.diagnostics.suppressedDuplicateBoxes,
      result.diagnostics.acceptedBoxes,
    );
    process.stdout.write(`${JSON.stringify({
      ok: true,
      fixtureId: metadata.id,
      lines: result.lines.length,
      detectionPasses: result.diagnostics.detectionPasses.length,
    })}\n`);
  } finally {
    await engine.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
