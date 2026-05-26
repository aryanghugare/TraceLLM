function parseSseChunk(chunk) {
  const lines = chunk.split(/\r?\n/);
  let event = "message";
  const dataLines = [];

  for (const line of lines) {
    if (line.startsWith("event:")) {
      event = line.slice(6).trim() || "message";
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trim());
    }
  }

  if (dataLines.length === 0) {
    return null;
  }

  const raw = dataLines.join("\n");
  let data = raw;

  try {
    data = JSON.parse(raw);
  } catch (error) {
    data = raw;
  }

  return { event, data };
}

export async function* parseSseStream(readable) {
  const reader = readable.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();

    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });

    let boundaryIndex = buffer.indexOf("\n\n");

    while (boundaryIndex !== -1) {
      const chunk = buffer.slice(0, boundaryIndex);
      buffer = buffer.slice(boundaryIndex + 2);

      const parsed = parseSseChunk(chunk);
      if (parsed) {
        yield parsed;
      }

      boundaryIndex = buffer.indexOf("\n\n");
    }
  }

  const finalChunk = buffer.trim();
  if (finalChunk) {
    const parsed = parseSseChunk(finalChunk);
    if (parsed) {
      yield parsed;
    }
  }
}
