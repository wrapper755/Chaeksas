// 그림 좌표(DI)가 없는 정의를 배치한다 (ADR-0088). `copy.mjs`가 esbuild로 묶어
// `vendor/bpmn-auto-layout.min.js`(전역 `ChkAutoLayout`)로 복사한다 — 캔버스 페이지가 쓴다.

import { BpmnModdle } from "bpmn-moddle";
import { layoutProcess } from "bpmn-auto-layout";

/**
 * 흐름의 `sourceRef`·`targetRef`로 노드의 `incoming`·`outgoing`을 채운다.
 * BPMN은 그 둘 없이도 올바르지만 배치기는 그것을 따라 걸어서, 없으면 선이 하나도 안 그어진다.
 */
function linkFlows(container) {
  for (const element of container.flowElements || []) {
    if (element.$type === "bpmn:SequenceFlow") {
      const { sourceRef: source, targetRef: target } = element;
      if (source) {
        source.outgoing = source.outgoing || [];
        if (!source.outgoing.includes(element)) source.outgoing.push(element);
      }
      if (target) {
        target.incoming = target.incoming || [];
        if (!target.incoming.includes(element)) target.incoming.push(element);
      }
    }
    if (element.flowElements) linkFlows(element);
  }
}

/** 다이어그램이 하나도 없는가 — **있으면 배치하지 않는다** (사람이 놓은 자리를 덮지 않는다). */
export async function needsLayout(xml) {
  const { rootElement } = await new BpmnModdle().fromXML(xml);
  return !(rootElement.diagrams && rootElement.diagrams.length);
}

/** DI를 지어 붙인 XML. 의미 모델은 `incoming`·`outgoing` 말고 건드리지 않는다. */
export async function layout(xml) {
  const moddle = new BpmnModdle();
  const { rootElement } = await moddle.fromXML(xml);
  for (const root of rootElement.rootElements || []) {
    if (root.$type === "bpmn:Process") linkFlows(root);
  }
  const { xml: linked } = await moddle.toXML(rootElement);
  return layoutProcess(linked);
}
