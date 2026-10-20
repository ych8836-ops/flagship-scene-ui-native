# 작성 채팅에 전달할 요청문

현재 UI에서 계획 JSON을 내보내고 참고 자료의 **등록 순서·실제 input 상대 파일명·이미지 내용**을 정리합니다. 아래 요청과 [전체 작성 규칙](../PROMPT_RULES_SEQUENCE_KO.md), 내보낸 JSON을 작성 채팅에 줍니다. LLM이 로컬 파일을 자동으로 알 수는 없습니다.

```text
Flagship Scene UI 작성 규칙과 첨부 계획 JSON을 기준으로 새 계획을 만들어줘.
스토리·전체 길이: [내용]
모드: [일반 / 시퀀스]
씬별 공간·시간·연출: [내용]
참고: [씬별 Picture 번호, 실제 파일명, 이미지 내용·인물 역할]
대사·음향: [화자, 정확한 대사, 감정, 소리]

1. Comfy 노드 연결 JSON이 아닌 settings/references/scenes/clips 계획을 출력한다.
2. 제공한 모델·LoRA 파일명, 샘플러·스텝·해상도를 임의 변경하지 않는다.
3. 시퀀스에서는 scene_id와 씬별 참고 순서를 유지하고 씬 클립은 연속 배치한다.
4. 같은 동작은 같은 씬에 연결하고 새 씬은 continue_previous:false를 기본으로 한다.
5. 공통 참고 사용 시 필요한 @picture_N만 각 클립에서 부른다.
   모든 인물·이미지를 shared_prompt에 일괄 나열하지 않는다.
6. subject_definitions, summary, retention_analysis, detailed_description,
   overall_soundscape, non_diegetic_music를 각 클립 프롬프트에 유지한다.
7. 대사와 동작이 seconds에 들어가는지 검토한다. 화자·배역·참고를 혼동하지 않는다.
8. 클립별 리파이너를 명시하고 기본 OFF로 한다. 자동 음성 LoRA 분리를 가정하지 않는다.
9. 없는 파일명·설정 키·모델·노드를 만들지 않는다.
10. 계획 JSON과 별도의 짧은 검수표를 준다.
```

새 작업 → JSON 불러오기 → 검증 → 실제 참고 선택·모델·해상도 확인 → Generate 순서로 사용합니다. JSON에는 미디어·가중치가 포함되지 않습니다. 이미 생성한 프로젝트는 선택 클립 에디터에서 수정합니다.
