import type { SourceDocument } from "../lib/api/client";
import { Code, Missing, Row } from "./ui";

/** A Source Document's accession, form (with its document type) and publisher, as table rows. */
export function SourceDocumentRows({ sourceDocument }: { sourceDocument: SourceDocument }) {
  return (
    <>
      <Row name="Accession">
        {sourceDocument.accession ? <Code>{sourceDocument.accession}</Code> : <Missing />}
      </Row>
      <Row name="Form">
        {sourceDocument.form_type ?? <Missing />}
        {sourceDocument.document_type &&
          sourceDocument.document_type !== sourceDocument.form_type &&
          ` (${sourceDocument.document_type})`}
      </Row>
      <Row name="Publisher">
        {sourceDocument.publisher} via {sourceDocument.provider}; tier{" "}
        {sourceDocument.source_tier}, licence {sourceDocument.license_class}
      </Row>
    </>
  );
}
