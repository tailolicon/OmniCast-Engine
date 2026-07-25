# OmniCast Engine — Strategic Review Brief

**Ngày tổng hợp:** 2026-07-23  
**Mục đích:** Handoff cho các Agent độc lập review, phản biện và đề xuất roadmap  
**Trạng thái:** Bản chẩn đoán, không phải đặc tả triển khai đã được phê duyệt

---

## 1. Mục tiêu thực sự của OmniCast

OmniCast không chỉ cần là một cỗ máy tự động sinh thật nhiều video. Mục tiêu thực sự là:

> Xây dựng, vận hành và phát triển các kênh YouTube như một đội ngũ gồm strategist, researcher, biên kịch, fact-checker, art director, editor, sound designer, thumbnail designer và channel manager.

Video đầu ra cần:

- Phù hợp đúng nhóm khán giả.
- Có chất lượng như một đội ngũ làm chỉn chu, tránh “AI slop”.
- Học được cấu trúc thành công của đối thủ mà không sao chép mù quáng.
- Biết lựa chọn production mode thích hợp cho từng niche và từng scene.
- Xây dựng kênh dài hạn, không chỉ săn một vài video viral.
- Sử dụng Shorts để thu hút và long-form để giữ chân/chuyển đổi người xem.
- Tìm niche dựa trên lợi thế thật sự của production stack.
- Tối ưu đồng thời chất lượng, chi phí, tốc độ, rủi ro và khả năng mở rộng.

Video benchmark do chủ hệ thống tự tạo và sở hữu:

```text
E:\Project\OmniCast Engine\YTDown.com_YouTube_1093-Bat-ChatGPT-Dem-1-1-Trieu-Cai-Gia-C_Media_ucqR7A7BelQ_001_1080p.mp4
```

---

## 2. Những gì OmniCast đã có

Không nên kết luận OmniCast “chưa có gì”. Hệ thống đã có nhiều bộ phận đáng giữ lại:

- Quét YouTube theo nhiều seed query.
- Quét hàng chục đến hàng trăm kênh.
- Phát hiện outlier theo median từng kênh.
- Có views/day, engagement, duration và subscriber tiers.
- Lọc Shorts, video cũ và một số thị trường không phù hợp.
- Phát hiện micro-outlier/supernova ở kênh nhỏ.
- Channel Architect có audience profile, pain points và content triggers.
- Học title playbook từ đối thủ.
- Phân tích thumbnail đối thủ bằng vision.
- Học hook/structure/pacing từ transcript nếu lấy được.
- Đưa playbook đối thủ vào writer và thumbnail/title generator.
- Pipeline media có TTS, stock footage, AI image, music, subtitle, thumbnail, render và audio mastering.
- Có analytics thật cho kênh sở hữu: views, watch time, AVD, retention, subscribers, traffic và revenue khi API cho phép.
- Có scheduler, upload guard, thumbnail A/B và strategist cơ bản.
- Đã có một số quy tắc Health/YMYL và citation cho nội dung nhạy cảm.

Vấn đề chính không phải thiếu mọi linh kiện, mà là:

> Các linh kiện chưa tạo thành một bộ não kinh doanh, nghiên cứu đối thủ và art-direction thống nhất.

---

## 3. Vấn đề về tìm niche

### 3.1. Công thức niche chưa đầy đủ

Một niche hấp dẫn phải được đánh giá theo ít nhất:

```text
Nhu cầu được chứng minh
× Nguồn cung yếu
× Audience fit
× Lợi thế sản xuất của OmniCast
× Monetization fit
× Khả năng xây dựng thư viện nội dung dài hạn
```

Scorer hiện tại chủ yếu dựa trên:

- Trend momentum.
- Outlier.
- RPM theo thị trường.
- Novelty so với knowledge base.

Nó chưa đo đúng:

- Số lượng và chất lượng đối thủ.
- Mức độ bao phủ của chủ đề.
- Chất lượng trung bình của nguồn cung.
- Chi phí sản xuất của đối thủ.
- Chi phí sản xuất của OmniCast.
- Khả năng OmniCast tạo nội dung mà con người làm rất đắt.
- Độ sâu của content universe.
- Khả năng phát triển thành series.
- Rủi ro pháp lý, YMYL và quyền sử dụng tài sản.
- Khả năng tạo returning viewers thay vì chỉ tạo một video viral.

### 3.2. `gap_score` đang double-count nhu cầu

Trong `implementation/src/omnicast/discovery/scorer.py`, outlier càng cao thì `gap_score` càng cao.

Như vậy `outlier_ratio` đang được sử dụng cho cả:

- Trend/demand.
- Gap/supply opportunity.

Một video outlier chứng minh nhu cầu, nhưng không tự động chứng minh nguồn cung yếu.

### 3.3. Thiếu production asymmetry/stack-fit

Ví dụ:

- Prehistoric storytelling.
- Các thời đại không có footage.
- Tái dựng lịch sử.
- Mô phỏng những khái niệm không thể quay.
- Nội dung cần hàng trăm illustration đồng nhất.

Đối thủ con người có thể cần animator và illustrator đắt tiền. OmniCast có thể tạo bằng image/video generation với chi phí thấp hơn nhiều.

Hiện scorer không biết lợi thế này. Nó cũng không biết khi nào niche cần:

- Stock footage.
- Expert footage.
- Character animation.
- Infographic.
- Historical reconstruction.
- Talking head.
- Motion design.

### 3.4. Vocabulary vẫn bị giới hạn

Nhận xét ban đầu rằng seed query “chỉ có finance/health” không còn hoàn toàn đúng: code hiện có finance, health, psychology, history, science, technology và lifestyle.

Tuy nhiên, danh sách vẫn hard-code trong:

```text
implementation/src/omnicast/discovery/niche_scanner.py
```

Hệ thống khó tự phát hiện các format chưa được gọi tên trước như:

- Prehistoric POV.
- Animated moral stories.
- Visualized expert debates.
- Simulation storytelling.
- Process reconstruction.
- Data-driven mini-documentary.

Cần vocabulary mở theo:

```text
subject × audience × promise × format × production advantage
```

### 3.5. Chưa phân biệt evergreen opportunity và trend spike

Mỏ vàng có thể là nhu cầu âm ỉ, bền vững nhưng khó sản xuất. Trend spike lại có thể rất đông đối thủ và hết hạn nhanh.

Hệ thống cần phân biệt:

- Evergreen demand.
- Seasonal demand.
- News-driven demand.
- Temporary trend.
- Repeatable series demand.
- Search demand.
- Browse/recommendation demand.

---

## 4. Vấn đề về phân tích đối thủ

### 4.1. Hai pipeline dùng hai định nghĩa “video thắng”

Discovery chọn outlier dựa trên median từng kênh. Đây là hướng đúng.

Nhưng `competitor_intel` lại lấy 30 video gần nhất rồi xếp theo views tuyệt đối:

```text
implementation/src/omnicast/analytics/competitor_intel.py
```

Hậu quả:

- Kênh lớn lấn át kênh nhỏ.
- Video cũ lấn át video mới.
- Playbook có thể học từ video views cao nhưng không phải outlier.
- Discovery tìm được video đúng nhưng writer/thumbnail lại học từ tập video khác.

### 4.2. Playbook bị lưu theo niche quá rộng

Competitor intelligence được key chủ yếu theo `niche`.

Nhưng trong cùng một niche có thể có nhiều:

- Nhóm tuổi.
- Mức độ hiểu biết.
- Format.
- Mục đích xem.
- Brand voice.
- Mức độ tin cậy cần thiết.

Ví dụ thumbnail finance cho người 25 tuổi không nên dùng cùng playbook với retirement finance cho người 65 tuổi.

Nên lưu theo:

```text
channel/archetype
+ audience segment
+ format
+ market
+ content pillar
```

### 4.3. Phân tích transcript quá hạn chế

Hiện hệ thống chỉ lấy khoảng 3.500 ký tự đầu mỗi video và tối đa một số ít transcript.

Thiếu:

- Full transcript.
- Chapter/beat segmentation.
- Re-hook giữa video.
- Placement của proof, CTA, objections và payoff.
- So sánh winner với video thất bại cùng kênh.
- ASR fallback khi transcript YouTube không tồn tại.
- Nhận diện claim, quote, nguồn và bằng chứng.
- Phân tích cách script phối hợp với hình và âm thanh.

### 4.4. Chưa phân tích comment đối thủ

Scanner chỉ lấy số lượng comment. Adapter lấy nội dung comment đang trả danh sách rỗng:

```text
implementation/src/omnicast/platforms/youtube.py
```

Do đó hệ thống chưa đọc được:

- Người xem thích phần nào.
- Họ không hiểu điều gì.
- Họ phản đối điều gì.
- Câu hỏi nào chưa được giải quyết.
- Chủ đề sequel nào được yêu cầu.
- Ngôn ngữ thật mà audience sử dụng.
- Các dấu hiệu mất niềm tin, clickbait hoặc thông tin sai.

### 4.5. Chưa có competitor research dossier thống nhất

Quy trình nghiên cứu đối thủ được tham khảo đề xuất một dossier gồm:

- Tổng quan kênh.
- Video data.
- Outliers.
- Title và hook.
- Thumbnail.
- Lịch đăng.
- Content pillars.
- Content gap.
- Dashboard.
- Spreadsheet.
- Master prompt.

OmniCast có nhiều dữ liệu thành phần nhưng chưa tổng hợp chúng thành một artifact thống nhất có:

- Evidence.
- Confidence.
- Nguồn dữ liệu.
- Trường nào đo thật.
- Trường nào suy luận.
- Trường nào đang thiếu.
- Recommendation có thể truy ngược về evidence.

### 4.6. Chưa phân tích lịch đăng thực sự

Scanner có `published_at`, nhưng scheduler dùng khung giờ hard-code theo thị trường:

```text
implementation/src/omnicast/upload/scheduler.py
```

Thiếu:

- Heatmap đối thủ.
- Hiệu suất theo ngày/giờ.
- Cadence theo content pillar.
- Khoảng nghỉ giữa các video.
- Tần suất series.
- So sánh lịch đăng với tuổi kênh và quy mô audience.
- Học lịch đăng từ dữ liệu thật của chính kênh.

Cũng cần tránh suy luận nhân quả: video thành công đăng lúc 8 giờ không có nghĩa 8 giờ tạo ra thành công.

### 4.7. Không được nhầm public metrics với dữ liệu nội bộ

Đối với đối thủ, YouTube public API không cung cấp đáng tin cậy:

- Impressions.
- CTR.
- Retention curve.
- Average view duration.
- Returning viewers.
- Subscriber conversion.
- Doanh thu thật.

Mọi suy luận từ các trường này phải được ghi là `estimated/inferred`, không được trình bày như dữ liệu thật.

### 4.8. Cần winner-vs-control, không chỉ học winner

Chỉ nhìn video thành công dễ dẫn đến survivorship bias.

Cần so sánh:

- Video thắng với video trung bình cùng kênh.
- Cùng pillar.
- Gần cùng thời điểm.
- Gần cùng duration.
- Cùng mức độ hỗ trợ từ brand/channel authority.

Mục tiêu là tìm yếu tố khác biệt, không chỉ mô tả đặc điểm phổ biến của video thắng.

---

## 5. Chưa có phân tích video theo nghĩa audiovisual forensics

Đây là khoảng trống lớn nhất.

`implementation/src/omnicast/analytics/video_intel.py` vẫn trả các giá trị placeholder như:

- Intro bằng 5% duration.
- Art direction là `cinematic`.
- Màu cố định.
- Music energy là `medium`.
- 150 words/minute.
- Hook type là `question`.
- Transition là `cut/fade`.

Hệ thống chưa thực sự đo:

- Shot boundaries.
- Thời lượng từng cảnh.
- Talking head/B-roll/stock/AI-image ratio.
- Zoom, pan, parallax.
- Motion graphics.
- Kinetic typography.
- Overlay và callout.
- Character consistency.
- Camera framing.
- Transition grammar.
- Nhịp dựng theo câu thoại.
- Nhạc vào/ra ở đâu.
- Silence.
- SFX type, timing và loudness.
- Voice pacing và emotional contour.
- Pattern interrupts.
- Joke visual và reaction beat.
- Cách title/thumbnail promise được payoff trong video.

Do đó OmniCast chưa thể:

> Xem một video đối thủ rồi tái tạo production grammar của nó.

---

## 6. Vấn đề với expert, người thật và nguồn tư liệu

Flow/image generation không thể là câu trả lời cho mọi asset.

Ví dụ nội dung tài chính hoặc sức khỏe cần:

- Ảnh thật của chuyên gia.
- Danh tính chính xác.
- Chức danh.
- Phát biểu nguyên bản.
- Nguồn và ngày phát biểu.
- Context của lời khuyên.
- Quyền sử dụng hình ảnh.

Không nên dùng ảnh AI giả chuyên gia hoặc tạo likeness mà người xem có thể hiểu nhầm là ảnh thật.

Cần một `Entity & Evidence Resolver`:

1. Nhận diện người, tổ chức, sự kiện và tài liệu.
2. Tìm asset thực được phép sử dụng.
3. Lưu provenance/license.
4. Xác minh quote.
5. Gắn citation vào script và scene.
6. Chặn render nếu quote, người và hình không khớp.

Đối với finance/health còn cần:

- Tách thông tin giáo dục khỏi lời khuyên cá nhân.
- Fact-check độc lập.
- Recency check.
- YMYL compliance.
- Disclaimer phù hợp.
- Không lấy authority của chuyên gia làm bằng chứng duy nhất.
- Không tạo fabricated expert endorsement.

---

## 7. Hệ thống chưa hỗ trợ nhiều production mode

Hiện pipeline mạnh nhất ở:

```text
voiceover + footage + AI images + captions + music
```

Nhưng các kênh thực tế có nhiều production grammar khác nhau:

- Footage-first documentary.
- Expert/evidence explainer.
- Infographic/motion design.
- Illustrated storytelling.
- Character animation.
- Hand-drawn comedy.
- Screen-record/tutorial.
- News montage.
- Talking head.
- Hybrid.

Hệ thống chưa có một router để quyết định:

```text
Scene này cần stock?
Ảnh thật?
Biểu đồ?
AI reconstruction?
Character animation?
Motion graphic?
Screen capture?
Hay không cần hình, chỉ cần khoảng lặng?
```

### 7.1. Animation là khoảng trống riêng

Các kênh kể chuyện vẽ tay thường có:

- Character rig.
- Pose library.
- Facial expressions.
- Lip sync.
- Squash-and-stretch.
- Anticipation.
- Timing hài.
- Prop interaction.
- Camera choreography.
- Keyframe và easing có chủ đích.

Sinh nhiều ảnh AI rồi crossfade không thể thay thế việc này.

Muốn phục vụ nhóm kênh đó cần một animation subsystem riêng, không phải chỉ nâng cấp prompt tạo ảnh.

---

## 8. Chưa đạt “95% giống video benchmark”

Với video do chủ hệ thống sở hữu, đạt độ tương đồng cao là khả thi nếu:

- Format lặp lại.
- Asset và font được phép tái sử dụng.
- Có template hóa.
- Reference video được phân rã theo timestamp.
- Chấp nhận xây renderer chuyên dụng cho format đó.

Nhưng “95%” hiện chưa có định nghĩa đo lường.

Cần chia thành:

- Script structure similarity.
- Visual source mix.
- Shot duration distribution.
- Caption/typography.
- Transition grammar.
- SFX placement.
- Music energy curve.
- Voice pacing.
- Color treatment.
- Thumbnail packaging.
- Overall perceived quality.

Pipeline hiện chưa tự động trích xuất đầy đủ các yếu tố này từ benchmark.

Không nên tuyên bố đạt 95% nếu chưa có:

- Golden reference.
- Metric từng chiều.
- Blind human comparison.
- Pass/fail threshold.
- Báo cáo những phần không thể hoặc không nên sao chép.

---

## 9. Vấn đề AI slop và quality assurance

Một video chất lượng không chỉ là “đủ script, voice và hình”.

Dấu hiệu AI slop thường gồm:

- B-roll đúng keyword nhưng sai ý.
- Hình AI đẹp nhưng không làm rõ câu thoại.
- Cảnh lặp lại.
- Nhân vật không đồng nhất.
- Chuyển động giả hoặc vô nghĩa.
- Quá nhiều zoom/crossfade.
- SFX generic.
- Nhạc không theo emotional beat.
- Voice đều và thiếu chủ ý.
- Caption/overlay dày đặc.
- Script nói nhiều nhưng không có proof.
- Fact có vẻ chính xác nhưng không truy vết được.
- Hook hứa quá mức.
- Không có editorial taste.

Một số quality module hiện vẫn placeholder hoặc trả điểm cố định. Test `video_intel` còn mock chính các phương thức cần kiểm tra, nên test pass không chứng minh analyzer hoạt động thật.

Thiếu các gate:

- Research accuracy.
- Source/provenance.
- Script editorial.
- Audience fit.
- Visual relevance.
- Continuity.
- Motion quality.
- Sound design.
- Packaging trust.
- YMYL/compliance.
- Benchmark comparison.
- Human review cho video rủi ro cao.

---

## 10. Thumbnail và audience customization chưa đủ sâu

Hệ thống đã có audience context trong writer và có nhánh packaging cho một vài format. Tuy nhiên chưa có một thumbnail strategy engine đầy đủ theo audience.

### Trẻ em/entertainment

Có thể phù hợp với:

- Expression lớn.
- Màu mạnh.
- Object phóng đại.
- Conflict rõ.
- Curiosity cao.
- Phong cách gần MrBeast.

### Finance cho người lớn tuổi

Có thể cần:

- Trust và authority.
- Typography rõ.
- Ít yếu tố.
- Con số cụ thể.
- Khuôn mặt đáng tin.
- Tránh biểu cảm quá lố.
- Tránh cảm giác scam.

### Health cho người cao tuổi

Cần:

- Dễ đọc.
- Bình tĩnh.
- Không gây hoảng sợ quá mức.
- Hình ảnh có tính xác thực.
- Người có chuyên môn.
- Claim thận trọng.

Audience profile phải điều khiển:

- Thumbnail.
- Title.
- Tone.
- Voice.
- Nhịp dựng.
- Text density.
- Music/SFX.
- CTA.
- Video length.
- Mức giải thích.
- Bằng chứng.
- Trust signals.

Không nên chỉ đưa audience vào prompt writer rồi coi là đã cá nhân hóa toàn hệ thống.

---

## 11. Thiếu tầm nhìn xây dựng kênh dài hạn

OmniCast hiện thiên về:

```text
tìm topic → sinh video → đăng → đo views
```

Nó chưa hành xử đầy đủ như một channel operator giàu kinh nghiệm.

### 11.1. Channel thesis

Thiếu câu trả lời rõ ràng cho:

- Kênh tồn tại để phục vụ ai?
- Lời hứa độc nhất là gì?
- Tại sao người xem quay lại?
- Moat của kênh là gì?
- Format nào được sở hữu lâu dài?

### 11.2. Content architecture

Cần quản lý:

- Core pillars.
- Supporting pillars.
- Experimental pillar.
- Recurring series.
- Seasonal series.
- Tentpole video.
- Evergreen library.
- Sequels và follow-ups.

### 11.3. Shorts → Long funnel

Thiếu chiến lược xác định:

- Shorts nào làm discovery.
- Shorts nào test hook/topic.
- Shorts nào cắt từ long-form.
- Shorts nào dẫn đến video long cụ thể.
- Long-form nào chuyển người xem thành returning viewers.
- Cách đo conversion Shorts → Long.

### 11.4. Audience journey

Cần phân loại:

```text
Cold viewer
→ casual viewer
→ subscriber
→ returning viewer
→ core fan
→ customer/community member
```

Mỗi giai đoạn cần nội dung, CTA và packaging khác nhau.

### 11.5. Experiment portfolio

Không nên tạo nhiều kênh và chờ một kênh “nổ”.

Cần stage gate:

- Niche validation.
- Format validation.
- Packaging validation.
- Retention validation.
- Audience return validation.
- Monetization validation.
- Scale/kill/pivot decision.

Có thể phân bổ tài nguyên kiểu:

- 70% proven.
- 20% adjacent experiments.
- 10% high-risk asymmetric bets.

Tỷ lệ cụ thể cần được kiểm chứng theo nguồn lực và giai đoạn của hệ thống.

### 11.6. Long-term metrics

Không chỉ views:

- Returning viewers.
- Subscriber conversion.
- Views per viewer.
- Series continuation rate.
- Search longevity.
- Browse dependency.
- Shorts-to-long conversion.
- Comment quality.
- Library compounding.
- Revenue per production hour.
- Cost per retained minute.
- Brand trust.

---

## 12. Kiến trúc đang phân mảnh

Hiện có nhiều module tốt nhưng chưa có một shared evidence model.

Cần một `CompetitorEvidenceGraph` hoặc SSOT tương đương để liên kết:

```text
Channel
→ Audience
→ Content pillar
→ Video
→ Topic
→ Title/thumbnail
→ Transcript beats
→ Visual/audio grammar
→ Public metrics
→ Inferred findings
→ Confidence
→ Source/provenance
→ Recommended production blueprint
```

Hiện tại:

- Discovery có dữ liệu outlier.
- Competitor intel có playbook.
- Channel Architect có audience fit.
- Writer có script.
- Clickbait có title/thumbnail.
- Video intel có blueprint placeholder.
- Scheduler có prime time hard-code.
- Analytics có dữ liệu kênh sở hữu.

Nhưng các module chưa cùng đọc một bằng chứng và cùng sử dụng một định nghĩa chiến thắng.

---

## 13. Silent degradation và trạng thái “hoàn thành” gây hiểu lầm

Nhiều đường code catch exception rồi trả chuỗi rỗng hoặc bỏ qua:

- Không lấy được transcript.
- Vision thất bại.
- API key thiếu.
- Competitor scan lỗi.

Pipeline có thể tiếp tục, nhưng người vận hành không biết chất lượng đã suy giảm.

Cần artifact ghi rõ:

```text
measured
inferred
estimated
missing
fallback_used
confidence
```

Ngoài ra, tài liệu trạng thái có xu hướng liệt kê module như đã có, trong khi implementation bên trong vẫn placeholder. Đây là rủi ro:

> Feature tồn tại trên sơ đồ nhưng chưa có năng lực thật.

Test chỉ xác nhận schema hoặc mock cũng không đủ để tuyên bố capability đã hoàn thành.

---

## 14. Những nhận định trước đó cần Agent khác phản biện

Không nên mặc định tất cả nhận định ban đầu đều đúng:

1. “Cả bốn chiều TopicScorer đều là tín hiệu cầu” là diễn đạt chưa chính xác. RPM và novelty không phải demand, nhưng đúng là chúng không đo nguồn cung hoặc stack-fit.

2. “Seed query chỉ có finance/health” đã lỗi thời. Hiện danh sách rộng hơn, nhưng vẫn hard-code.

3. “Trend cao luôn là nơi đông đối thủ nhất” không phải lúc nào cũng đúng. Một micro-channel có outlier lớn có thể là tín hiệu thiếu cung.

4. “Không có stock footage bị scorer xem là điểm trừ” chưa thấy bằng chứng trực tiếp trong scorer. Vấn đề đúng hơn là scorer hoàn toàn không nhận ra đó có thể là lợi thế của AI reconstruction.

5. Quy trình nghiên cứu 5–7 kênh là hướng tốt, nhưng con số 5–7 không tự động bảo đảm chất lượng. Cách chọn cohort quan trọng hơn số lượng.

6. Master prompt không phải chiến lược. Nó chỉ là artifact sau khi research đúng.

7. Video outlier không chứng minh mọi yếu tố của title, thumbnail, lịch đăng và nội dung đều tốt. Cần matched comparison.

8. “Làm giống 95%” cần định nghĩa theo từng chiều, không thể đánh giá chỉ bằng cảm giác.

---

## 15. Hạng mục ưu tiên đề xuất

Đề nghị các Agent đánh giá lại thứ tự, nhưng hiện tại top ưu tiên là:

### P0 — Hợp nhất competitor intelligence

- Dùng chung outlier cohort.
- Winner vs matched-control.
- Views/day và tuổi video.
- Full transcript + ASR fallback.
- Content pillar.
- Comments.
- Schedule.
- Evidence/confidence.
- Dossier thống nhất.

### P0 — Sửa niche opportunity model

```text
demand
+ supply weakness
+ audience fit
+ stack-fit
+ monetization
+ repeatability
- production/legal/YMYL risk
```

### P0 — Production mode router

Phân loại scene và chọn đúng giữa:

- Real evidence.
- Stock.
- AI illustration.
- Reconstruction.
- Infographic.
- Animation.
- Screen capture.
- Talking head.

### P1 — Audiovisual forensic analyzer

Trích xuất timestamp-level:

- Shot.
- Motion.
- Text.
- Transition.
- Music.
- SFX.
- Voice pacing.
- Production grammar.

### P1 — Audience-specific channel strategy

- Channel thesis.
- Pillars.
- Series.
- Shorts-long funnel.
- Packaging profile.
- Stage gates.
- Experiment portfolio.

### P1 — Quality and benchmark gates

- Không dùng fixed score.
- So sánh với reference/golden set.
- Đo từng chiều cụ thể.
- Human approval cho YMYL và video flagship.

### P2 — Animation subsystem

- Character bible.
- Pose/expression library.
- Rigging.
- Lip sync.
- Keyframes.
- Motion grammar.
- Continuity.

---

## 16. Câu hỏi dành cho các Agent độc lập

Hãy review repo và phản biện bản chẩn đoán này. Không mặc định các kết luận ở trên là đúng.

Yêu cầu trả lời:

1. Những finding nào được code xác nhận?
2. Finding nào sai, lỗi thời hoặc bị phóng đại?
3. Có vấn đề quan trọng nào bị bỏ sót?
4. Điểm nghẽn lớn nhất hiện tại là discovery, strategy, editorial hay production?
5. OmniCast nên tự xây gì và tích hợp công cụ ngoài cho phần nào?
6. Kiến trúc SSOT/evidence graph nên thiết kế thế nào?
7. Làm thế nào đo “giống benchmark 95%” bằng tiêu chí khách quan?
8. Nên ưu tiên nâng chất lượng một kênh hay tiếp tục multi-channel?
9. Roadmap P0/P1/P2 hợp lý nhất là gì?
10. Hạng mục nào có ROI cao nhất trong 30 ngày?
11. Hạng mục nào có vẻ hấp dẫn nhưng không nên xây?
12. Những rủi ro về copyright, likeness, YMYL và YouTube policy còn thiếu?
13. Đề xuất test/benchmark nào chứng minh capability chạy thật thay vì chỉ có module?
14. Đưa ra top 5 thay đổi có tác động lớn nhất, kèm file/module cần sửa.
15. Nếu bất đồng với chẩn đoán, hãy nêu bằng chứng code cụ thể.
16. OmniCast nên dùng một global channel với multi-language audio, nhiều local channel, hay mô hình lai?
17. Tiêu chí định lượng nào quyết định lúc cần tách một ngôn ngữ thành local channel?
18. YouTube Data API, Studio automation và bước review thủ công nên chia trách nhiệm thế nào cho multilingual publishing?
19. Làm sao kiểm chứng bản dịch tài chính theo quốc gia mà không làm chi phí vận hành vượt quá giá trị audience mới?

---

## 17. Các file nên kiểm tra trước

```text
implementation/src/omnicast/discovery/scorer.py
implementation/src/omnicast/discovery/niche_scanner.py
implementation/src/omnicast/discovery/youtube_scanner.py
implementation/src/omnicast/agents/channel_architect.py
implementation/src/omnicast/analytics/competitor_intel.py
implementation/src/omnicast/analytics/video_intel.py
implementation/src/omnicast/agents/writer.py
implementation/clickbait.py
implementation/src/omnicast/upload/scheduler.py
implementation/src/omnicast/platforms/youtube.py
implementation/src/omnicast/analytics/crawler.py
IMPLEMENTATION_STATUS.md
PROJECT_CONTEXT.md
Plans.md
```

---

## 18. Multilingual distribution và country localization

### 18.1. Cơ hội kinh doanh

Một video finance bằng tiếng Anh cho người lớn tuổi có thể giải quyết vấn đề mà người xem tại Đức, Thụy Điển, Đan Mạch và các quốc gia khác cũng gặp phải. Rào cản ngôn ngữ làm giảm:

- Khả năng click.
- Mức hiểu nội dung.
- Retention.
- Trust.
- Khả năng người xem áp dụng lời khuyên.

OmniCast vì vậy cần coi multilingual distribution là một capability chiến lược, không chỉ là một tùy chọn TTS.

### 18.2. Video tiếng Anh vẫn có thể được đề xuất xuyên ngôn ngữ

Recommendation của YouTube không có hàng rào cứng ngăn video tiếng Anh xuất hiện với người xem ngôn ngữ khác. Hệ thống recommendation chủ yếu dựa vào:

- Watch history.
- Search history.
- Subscriptions.
- Likes/dislikes.
- Satisfaction signals.

Tuy nhiên, nếu người xem không hiểu tiếng Anh, họ có thể không click hoặc rời video sớm. Điều này tạo satisfaction signal yếu và làm hạn chế phân phối thực tế cho nhóm tương tự.

Translated title/description giúp video xuất hiện trong tìm kiếm địa phương. Multi-language audio còn cho phép cùng một video phát track phù hợp với ngôn ngữ người xem, đồng thời giữ views và watch time trên cùng video.

### 18.3. Một kênh hay nhiều kênh?

Đề xuất mô hình lai:

> Một global channel với multi-language audio cho nội dung phổ quát; local channel cho nội dung thay đổi theo luật, thuế, sản phẩm tài chính, văn hóa và chiến lược audience.

#### Một video, nhiều audio track

Phù hợp khi:

- Ý nghĩa và kết luận không đổi.
- Chỉ cần dịch ngôn ngữ và thuật ngữ.
- Visual có thể dùng chung.
- Không phụ thuộc luật hoặc sản phẩm địa phương.
- Audience promise giống nhau.

Ví dụ:

- Tâm lý khi nghỉ hưu.
- Cách tránh scam nhắm vào người lớn tuổi.
- Longevity risk.
- Lạm phát và sức mua.
- Cách đánh giá một cố vấn tài chính.

#### Country-specific video variant

Cần khi khác biệt địa phương làm thay đổi:

- Điều kiện nhận lương hưu.
- Tuổi nghỉ hưu.
- Thuế.
- Mức đóng góp.
- Cách rút tiền.
- Bảo hiểm y tế.
- Trợ cấp.
- Deadline.
- Sản phẩm tài chính.
- Cơ quan quản lý.
- Hành động người xem nên thực hiện.
- Citation và chuyên gia được sử dụng.

Ví dụ:

| Nội dung | Phương án |
|---|---|
| Tâm lý khi chuyển sang sống bằng tiền hưu trí | Cùng video, nhiều audio |
| Cách tránh scam đầu tư | Cùng video, nhiều audio |
| Khi nào nhận Social Security | Video Mỹ riêng |
| Thuế khi rút 401(k)/Roth IRA | Video Mỹ riêng |
| Gesetzliche Rente/Riester/Rürup | Video Đức riêng |
| Quy định pension Thụy Điển | Video Thụy Điển riêng |
| Thuế hưu trí Đan Mạch | Video Đan Mạch riêng |

### 18.4. Không cần sản xuất lại toàn bộ video địa phương

Video nên được thiết kế theo module:

```text
GLOBAL CORE
├── Hook phổ quát
├── Vấn đề chung
├── Nguyên tắc tài chính
├── Psychology/risk
│
└── LOCAL MODULE
    ├── Luật địa phương
    ├── Cơ quan và sản phẩm
    ├── Ví dụ bằng đồng tiền địa phương
    ├── Chuyên gia/nguồn địa phương
    ├── Hành động cụ thể
    └── Disclaimer
```

OmniCast có thể tái sử dụng:

- Research phổ quát.
- Phần lớn script.
- Footage.
- Animation.
- Music.
- Template.
- Một phần thumbnail.

Sau đó chỉ thay:

- Local script module.
- Voice.
- Text overlay.
- Biểu đồ và con số.
- Caption.
- Citation.
- Thumbnail.
- Title/description.

Kết quả là các video file riêng nhưng không phải làm lại từ đầu.

### 18.5. Lồng tiếng có thể lệch timeline

Các ngôn ngữ không có cùng độ dài câu. Một câu tiếng Anh dài 6 giây có thể thành câu tiếng Đức dài 8 giây.

Rủi ro:

- Hình xuất hiện trước hoặc sau ý đang nói.
- Biểu đồ đổi khi voice chưa nói xong.
- Reveal và SFX lệch nhịp.
- Caption/callout sai thời điểm.
- Music ducking không còn đúng.
- Talking head và animation lệch khẩu hình.

Mức độ rủi ro:

| Format | Nguy cơ lệch |
|---|---:|
| Voice-over + B-roll tổng quát | Thấp |
| Documentary đổi cảnh theo từng ý | Trung bình |
| Infographic/data visualization | Cao |
| Kinetic text bám từng câu | Rất cao |
| Expert/talking head | Rất cao |
| Character animation/lip-sync | Rất cao |

### 18.6. Dubbing pipeline phải time-aware

Không được dùng pipeline đơn giản:

```text
dịch literal → TTS → upload
```

Cần:

```text
Script gốc có timestamp
→ dịch theo meaning + duration
→ tạo voice
→ đo duration thật
→ rewrite-to-fit
→ forced alignment
→ căn lại caption và visual cue
→ remix BGM/SFX theo voice mới
→ kiểm tra cue drift
→ xuất full audio track cùng duration video
```

Mỗi đoạn script cần time budget:

```json
{
  "scene": 12,
  "start": 83.2,
  "end": 91.0,
  "max_voice_duration": 7.4,
  "visual_cues": [
    {"time": 85.0, "event": "show retirement balance"},
    {"time": 89.2, "event": "highlight 4%"}
  ]
}
```

Translator phải giữ ý nghĩa và làm câu vừa time budget, thay vì dịch từng chữ.

Mỗi ngôn ngữ cần một bản mix hoàn chỉnh:

- Voice bản địa.
- BGM.
- SFX.
- Ducking theo voice mới.
- Silence.
- Transition.
- Loudness mastering.

Không nên chỉ upload voice riêng vì alternate track thay thế toàn bộ audio đang phát.

### 18.7. Không nên tăng tốc voice quá mạnh

TTS có thể điều chỉnh tốc độ nhẹ, nhưng ép câu dài bằng tốc độ quá cao sẽ:

- Khó nghe với người lớn tuổi.
- Làm giọng thiếu tự nhiên.
- Giảm trust.
- Phá nhịp nghỉ.
- Làm automatic dubbing khó hiểu.

Thứ tự xử lý:

1. Rewrite câu.
2. Điều chỉnh pause.
3. Điều chỉnh tốc độ nhẹ.
4. Stretch audio một lượng nhỏ.
5. Nếu vẫn không khớp, render localized video variant.

Ngưỡng QA đề xuất:

- Cue quan trọng lệch không quá khoảng 250–300 ms.
- Scene thông thường lệch không quá khoảng 500 ms.
- Tổng audio khớp chính xác duration video.
- Không câu nào bị cắt.
- Không tăng tốc đến mức ảnh hưởng khả năng hiểu.

### 18.8. Talking head và expert footage cần xử lý riêng

Nếu chuyên gia thật xuất hiện và nói trực tiếp:

- Giữ audio gốc nhỏ bên dưới và dùng voice-over dịch theo phong cách phóng sự; hoặc
- Giữ nguyên audio chuyên gia và thêm subtitle bản địa.

Không nên tạo cảm giác chuyên gia thật sự nói một ngôn ngữ mà họ không nói, đặc biệt với lời khuyên tài chính.

Nếu nội dung phụ thuộc mạnh vào khẩu hình, text hoặc cue chính xác, cần render video variant thay vì chỉ thay audio.

### 18.9. Automatic dubbing không đủ cho finance

Automatic dubbing có thể sai:

- Proper nouns.
- Tên cơ quan.
- Tên sản phẩm tài chính.
- Jargon.
- Thành ngữ.
- Phát âm.
- Context pháp lý.

Vì finance là YMYL, mọi dub cần:

- Manual review trước publication.
- Native reviewer hiểu lĩnh vực.
- Pronunciation glossary.
- Fact/citation review theo quốc gia.
- Cơ chế unpublish/replace khi phát hiện lỗi.

Automatic dubbing từ tiếng Anh hiện hỗ trợ một số ngôn ngữ như tiếng Đức, nhưng không nên giả định mọi ngôn ngữ đều được hỗ trợ. Khi auto-dub không có hoặc chất lượng không đạt, OmniCast phải tạo custom audio track.

### 18.10. OmniCast hiện chưa có multilingual publishing hoàn chỉnh

Uploader hiện mới đặt:

```text
defaultLanguage
defaultAudioLanguage
```

trong:

```text
implementation/src/omnicast/upload/youtube_api.py
```

Chưa thấy implementation hoàn chỉnh cho:

- Nhiều audio track trên cùng video.
- Localized title/description.
- Localized thumbnail.
- Per-language subtitle.
- Dub review workflow.
- Pronunciation glossary.
- Audio alignment.
- Per-language audio remix.
- Analytics theo audio language.
- Quyết định `translate`, `localize` hay `split channel`.
- Country-specific compliance.

YouTube Data API hỗ trợ localized title/description, nhưng OmniCast chưa sử dụng phần `localizations`. Alternate audio track có thể cần YouTube Studio automation hoặc bước vận hành riêng nếu public API không cung cấp endpoint phù hợp.

### 18.11. Capability cần bổ sung

Đề xuất `Multilingual Distribution Engine`:

```text
Language Opportunity Scorer
→ Universal-vs-Local classifier
→ Jurisdiction Router
→ Script translation/localization
→ Country-specific fact/compliance check
→ Stable voice per language
→ Pronunciation QA
→ Duration alignment
→ Per-language audio remix
→ Subtitle generation
→ Localized metadata
→ Localized thumbnail
→ Multi-track/variant publishing
→ Performance by audio language
→ Split-channel decision
```

### 18.12. Stage-gate mở local channel

Không nên mở hàng loạt channel chỉ vì có thể tạo dub.

Đầu tiên:

1. Chọn một hoặc hai ngôn ngữ.
2. Dub một nhóm video evergreen phổ quát.
3. Localize title, description và thumbnail.
4. Đo views/watch time theo audio language và geography.
5. Đọc comment/search demand địa phương.
6. Chỉ tách channel khi có demand và đủ cadence.

Nên tách local channel khi:

- Nội dung địa phương tạo thành một content pillar riêng.
- Phần lớn video phải đổi luật/nguồn/visual.
- Audience packaging khác đáng kể.
- Có đủ tài nguyên duy trì lịch đăng đều.
- Dữ liệu đã chứng minh demand.

### 18.13. Quy tắc quyết định cô đọng

> Nếu chỉ đổi ngôn ngữ, giữ cùng video. Nếu đổi luật làm thay đổi sự thật, con số, nguồn hoặc hành động được khuyến nghị, tạo country-specific video variant. Khi các variant tạo thành một catalogue đủ sâu, tách local channel.

---

## 19. Script Engine: chất lượng cạnh tranh và false-positive release

### 19.1. Câu hỏi chiến lược được đặt ra

Ngày 2026-07-23, Script Engine được review theo hai câu hỏi:

1. Các script hiện tại đã đủ sức cạnh tranh với những kênh kể chuyện horror hàng đầu cùng format chưa?
2. Làm thế nào sửa lỗi logic, giọng kể đồng dạng và premise rập khuôn mà không biến hệ thống thành máy viết theo checklist?

Mốc so sánh trực tiếp phù hợp là các kênh kể “true scary experiences” như Mr. Nightmare và Let’s Read. Đây là benchmark về:

- Giọng người bình thường kể lại.
- Logic đời thường.
- Dread có tiến triển.
- Ba truyện trong một compilation thực sự khác nhau.
- Một video có giá trị riêng, không chỉ thay địa điểm cho cùng một bộ xương truyện.

### 19.2. Kết quả review sáu artifact

Thư mục được kiểm tra:

```text
implementation/output/_review_pass
```

Phán quyết độc lập:

| Artifact | Điểm cạnh tranh ước lượng | Phán quyết |
|---|---:|---|
| `03 diner` | 80–83 | Gần đạt nhất; truyện 1 có khả năng cạnh tranh riêng lẻ, nhưng cả compilation vẫn cần sửa |
| `04 ranger` | 72–76 | Không khí ổn nhưng ba giọng và ending shape quá giống |
| `05 mall` | 70–74 | Dễ nghe nhưng công thức, supernatural devices bị chất chồng |
| `01 ranch/storage` | 68–73 | Văn trau chuốt nhưng không giống lời kể tự nhiên; có hành vi thiếu hợp lý |
| `06 hotel` | 62–68 | Có mâu thuẫn không gian nghiêm trọng ở truyện 2 |
| `02 newspapers` | 55–61 | Không nên phát hành; lỗi geometry, topic mismatch và ba truyện chung một causal skeleton |

Không có artifact nào đủ chắc để cạnh tranh ngang với video mạnh của kênh đầu ngành ở trạng thái hiện tại. `03 diner` là bản duy nhất đáng đầu tư một vòng rewrite có mục tiêu.

### 19.3. Các lỗi hệ thống đã để lọt

#### Physical và spatial continuity

- `newspapers`: nhân vật đứng kín giữa hai hàng rào nhưng narrator vẫn đi thẳng qua vai.
- `hotel`: ba người đang ở trong lobby, nhưng sau khi narrator khóa cửa họ lại đập kính như đang ở ngoài.

Đây là lỗi dựng cảnh, không phải lỗi văn phong. `continuity_ledger` hiện kiểm fact nhưng chưa mô phỏng đầy đủ chuyển trạng thái.

#### Plausible human response

- Nhân vật có bằng chứng nhưng cố tình không cho quản lý xem chỉ để giữ bí ẩn.
- Người lạ đã xâm nhập trạm ranger nhưng narrator không dùng radio hoặc gọi hỗ trợ.
- Một số escape/action chỉ tồn tại vì cốt truyện cần, không phải vì người thật có lý do chọn như vậy.

#### Voice sameness

Nhiều lineup có ba narrator khác lý lịch nhưng gần như cùng:

- Độ dài câu.
- Mức trau chuốt.
- Phép so sánh.
- Cách trì hoãn nhận thức nguy hiểm.
- Coda “từ đó tôi luôn...” hoặc một thói quen bị thay đổi.

`03 diner` có voice separation rõ nhất, nhưng giọng thiếu niên lại bị đẩy quá mạnh, tạo cảm giác model đang cố biểu diễn một voice profile.

#### Causal sameness

Đổi `threat_mechanism`, `escape_mechanism` hoặc địa điểm không bảo đảm originality. Nhiều truyện vẫn có chung trải nghiệm:

```text
người lạ/hiện tượng xuất hiện
→ narrator chần chừ
→ mối đe dọa tiến gần
→ narrator chạy tới nơi sáng/có người
→ cảnh sát không tìm thấy gì
→ narrator đổi một thói quen
```

Đây là nguyên nhân các artifact có thể pass typed diversity nhưng vẫn bị người nghe cảm nhận là rập khuôn.

### 19.4. Điểm nội bộ đang bị calibration cao

Các nhãn 84, 85, 88, 89 hoặc 93 trong artifact không tương ứng trực tiếp với sức cạnh tranh.

Hai false positive rõ nhất:

- `newspapers` được 93 nhưng có lỗi vật lý, topic mismatch và cấu trúc lặp.
- `hotel` được coi là content-valid dù blocking của truyện 2 không thể dựng nhất quán.

Deterministic gates hiện bắt tốt:

- Exact phrase.
- Một số AI tic.
- Forbidden ending.
- Một số cross-story repetition.

Nhưng chưa bắt ổn định:

- Geometry.
- Causal state.
- Lựa chọn hợp lý theo nghề.
- Giọng kể giống nhau ở cấp trải nghiệm.
- Cùng một story skeleton được paraphrase.

Vì vậy, `gate clean` không được dùng như bằng chứng rằng artifact đã competitive hoặc production-ready.

### 19.5. Nguy cơ hệ thống tự khóa sáng tạo

Rủi ro không nằm ở continuity gate. Logic chặt không làm giảm sáng tạo.

Rủi ro nằm ở việc biến mọi tín hiệu phong cách thành hard ban:

- Giới hạn “the way”.
- Giới hạn one-word beat.
- Cấm ngày càng nhiều coda.
- Blacklist trope tăng vô hạn.
- Ép mọi truyện khác nhau trên mọi enum.
- Ép narrator khác nhau bằng thống kê bề mặt.

Nếu tiếp tục theo hướng này, writer sẽ hội tụ về một vùng “median an toàn”: không phạm câu cấm nhưng thiếu cá tính. Điều này vừa giảm sức cạnh tranh vừa tăng tín hiệu content template.

### 19.6. Kiến trúc sửa đề xuất

Tách rule thành ba lớp:

#### Hard gate

Giữ cứng:

- Physical/timeline continuity.
- State của cửa, đạo cụ, người và lối thoát.
- Plausible response.
- Topic fidelity.
- Safety.
- Rights, impersonation và truth labeling.

#### Soft editorial signal

Không hard-block chỉ vì một occurrence:

- Phrase/tic.
- One-word beat.
- Coda family.
- Sentence length.
- Một trope quen.

Chỉ chặn khi tín hiệu lặp trong lineup hoặc tích lũy xuyên nhiều video.

#### Creative variables

Không đóng vocabulary quá sớm. Writer nên nhận positive brief gồm:

- Narrator dossier.
- Mục tiêu thực tế.
- Không gian.
- Causal spine.
- Kiến thức riêng do nghề nghiệp/đời sống.
- Một chi tiết đời thường không cần payoff.
- Một vùng không được giải thích.

Các detector phong cách nên chạy sau prose và chỉ trả lại lỗi thực sự xuất hiện, thay vì phát toàn bộ blacklist cho writer trước khi viết.

### 19.7. Capability cần bổ sung cho Script Engine

1. **Premise portfolio:** sinh 8–12 hạt truyện ngắn, tuyển premise rồi mới mua prose.
2. **Scene-state simulator:** theo dõi người, cửa, vật, vị trí, thời gian, khả năng liên lạc và chuyển trạng thái sau mỗi action.
3. **Causal fingerprint xuyên video:** lưu nghề, geometry, discovery channel, decision, escalation, escape, evidence, aftermath, ending image và voice cadence.
4. **Semantic memory 50–100 truyện:** không chỉ nhớ hai enum trong 20 video.
5. **Near-duplicate hard block:** chặn causal skeleton gần như trùng; similarity vừa phải chỉ trừ điểm.
6. **Wildcard allocation:** dành một phần premise được phép phá soft rules nhưng không phá logic/safety.
7. **Blind benchmark:** reviewer không thấy điểm cũ hoặc nhãn `released/content_valid` trước khi chấm.
8. **Calibration set:** lưu cả artifact tốt, false positive và lỗi geometry để đo precision/recall của release gate.

### 19.8. Các câu hỏi Script Engine còn cần Agent phản biện

1. Texture budget hiện giúp giảm AI tic hay đang ép prose về median an toàn?
2. Originality nên có hard floor hay nên được đánh giá bằng channel-level semantic distance?
3. Closed vocabulary năm trục đang đo narrative diversity hay chỉ đo label diversity?
4. Có nên cho phép premise quen nếu causal turn, narrator knowledge và ending đủ riêng?
5. `continuity_ledger` nên nâng thành state machine như thế nào?
6. Bộ nhớ xuyên video nên dùng cửa sổ cố định, decay theo thời gian hay kết hợp cả hai?
7. Release challenger cần nhìn riêng script hay phải nhìn cả title, thumbnail, voice và visual plan?
8. Tỷ lệ premise proven/experimental/wildcard nào cho hiệu quả tốt nhất?

---

## 20. YouTube 2026: inauthentic content, AI và rủi ro cấp hệ thống

### 20.1. Điều chính sách thực sự cấm

Chính sách YouTube hiện hành làm rõ rằng nội dung không được:

- Mass-produced.
- Generic.
- Repetitive.
- Manipulative.
- Dùng storyline/template khiến nhiều video có thể thay thế lẫn nhau.
- Dùng AI template chung chung tạo cảm giác sản xuất hàng loạt mà không có creative perspective.
- Dùng image slideshow, templated storyline hoặc scrolling text với ít narrative/commentary/value.

Reviewer có thể kiểm tra ở cấp toàn kênh:

- Main theme.
- Video nhiều view.
- Video mới nhất.
- Phần lớn watch time.
- Title, thumbnail và description.
- About section.

Nguồn chính thức:

- <https://support.google.com/youtube/answer/1311392>
- <https://support.google.com/youtube/answer/14328491>
- <https://support.google.com/youtube/answer/1727191>
- <https://support.google.com/youtube/answer/2802168>

### 20.2. AI không bị cấm mặc định

YouTube cho phép dùng AI để:

- Hỗ trợ outline và script.
- Tạo title, thumbnail hoặc infographic.
- Chỉnh sửa và hoàn thiện một narrative độc đáo.
- Tạo background visual hoặc hình minh họa có giá trị sáng tạo.
- Clone chính giọng của creator cho voice-over/dub trong các trường hợp được chính sách cho phép.

Điểm quyết định là thành phẩm cuối:

> Có thể hiện creative vision và mang lại giá trị giải trí/giáo dục riêng hay chỉ giống output của một production template?

Do đó, rủi ro của OmniCast không phải “có dùng AI”, mà là toàn bộ output có tạo cảm giác một dây chuyền tự động thay danh từ rồi xuất bản hay không.

### 20.3. AI persona nhạy cảm

AI-generated persona giả làm chuyên gia để tư vấn:

- Y tế.
- Pháp lý.
- Tài chính.
- Chính trị.

có thể không đủ điều kiện kiếm tiền.

Điều này đặc biệt liên quan đến các ý tưởng finance/health của OmniCast. Không được tạo “bác sĩ”, “cố vấn tài chính” hoặc “luật sư” AI khiến người xem tin đó là người thật có thẩm quyền.

Đối với horror, rủi ro chính là:

- Nhái giọng/likeness của người thật.
- Trình bày nhân vật hư cấu như nhân chứng có thật có thể kiểm chứng.
- Dùng realistic synthetic footage nhưng không disclosure.
- Dùng shock/manipulation thay cho một narrative có giá trị.

### 20.4. Truth labeling cho True Dread Files

Nếu câu chuyện do hệ thống sáng tác, không nên khẳng định chắc chắn:

```text
true submissions from real people
```

Hai framing ít rủi ro hơn:

```text
Original first-person horror fiction
```

hoặc:

```text
Dramatized encounters inspired by real-world situations
```

Nếu dùng submission thật:

- Lưu permission.
- Lưu nguồn.
- Ghi mức độ adaptation.
- Không đọc lại gần nguyên văn nội dung website/Reddit rồi coi là original.

### 20.5. Synthetic-content disclosure

AI hỗ trợ script, outline hoặc title không tự động bắt buộc disclosure.

Phải disclosure khi dùng AI để:

- Tạo cảnh photorealistic giống một sự kiện đã xảy ra dù thực tế không xảy ra.
- Làm người thật nói/làm điều họ không làm.
- Thay đổi đáng kể footage của địa điểm hoặc sự kiện thật.

YouTube nêu rõ việc bật disclosure không tự động làm giảm eligibility kiếm tiền. Vì vậy không nên né nhãn khi thuộc diện phải khai báo.

### 20.6. Rủi ro “trừng phạt liên đới” cần diễn đạt chính xác

Không có bằng chứng chính thức rằng một video limited ads hoặc một lần YPP từ chối sẽ tự động giết mọi kênh liên quan.

Tuy nhiên:

- Vi phạm monetization nghiêm trọng có thể làm mất kiếm tiền trên tất cả hoặc một số tài khoản.
- Community Guidelines strike, copyright strike và visual khớp third-party content có thể góp phần làm các tài khoản liên quan bị đình chỉ kiếm tiền.
- Khi một kênh bị terminate, chủ kênh bị cấm dùng, sở hữu hoặc tạo kênh khác để lách termination; quy tắc áp dụng cho kênh hiện có, kênh mới và kênh nơi người đó xuất hiện nổi bật/lặp lại.

Vì vậy, về vận hành phải coi toàn bộ portfolio channel là một risk domain. Không nên dùng channel mới để cô lập hoặc lách một vi phạm đã biết.

### 20.7. Script pass không đủ bảo vệ YPP

YouTube đánh giá thành phẩm và toàn kênh. OmniCast cần một production-level authenticity audit gồm:

- Script causal similarity.
- Narrator/voice similarity.
- Title template similarity.
- Thumbnail composition similarity.
- Visual source mix.
- Shot duration và transition grammar.
- Tỷ lệ ảnh tĩnh.
- Music/SFX reuse.
- Upload portfolio.
- Description/About truthfulness.
- AI disclosure.
- Asset rights/provenance.

Một script khác biệt nhưng được dựng bằng cùng 15 ảnh, cùng pan/zoom, cùng TTS cadence và cùng thumbnail template vẫn có thể tạo cảm giác mass-produced.

### 20.8. Horror và advertiser suitability

Horror không mặc định mất quảng cáo. Rủi ro tăng khi:

- Gore hoặc thương tích là trọng tâm.
- Thumbnail/title cố gây sốc hoặc ghê tởm.
- Bạo lực được mô tả chi tiết không có context.
- Trẻ em hoặc nhân vật giống trẻ em bị đặt trong cảnh distress/gore.
- Nội dung dùng một sensitive event thật để câu traffic.

True Dread Files nên ưu tiên:

- Threat không graphic.
- Dread từ logic và không gian.
- Không khai thác nạn nhân/sự kiện thật đang nhạy cảm.
- Thumbnail gợi bất an thay vì gore.
- Metadata không hứa quá mức so với nội dung.

### 20.9. Kiến trúc phòng thủ không khóa sáng tạo

OmniCast nên chuyển từ:

```text
generate một bản
→ sửa đến khi pass checklist
```

sang:

```text
sinh portfolio premise rộng
→ loại premise phi logic/chính sách
→ chọn premise có giá trị riêng
→ viết bằng positive brief
→ audit causal + semantic + production
→ chỉ release thành phẩm có dấu ấn rõ
```

Nguyên tắc:

- Hard gate tạo biên an toàn.
- Soft rule bảo vệ độ tự nhiên nhưng không quyết định nghệ thuật.
- Semantic memory bảo vệ channel khỏi tự lặp.
- Wildcard bảo vệ hệ thống khỏi hội tụ.
- Production audit bảo vệ YPP ở cấp thành phẩm.

### 20.10. Provenance package cho mỗi video

Mỗi release nên lưu:

- Nguồn premise/submission.
- Permission nếu có.
- Script versions và editorial changes.
- Asset source/license.
- Voice provenance.
- Shot plan.
- AI disclosure decision.
- Fact/citation ledger.
- Similarity report với video cũ.
- Final policy self-certification.

Provenance không bảo đảm YouTube sẽ phê duyệt, nhưng tạo bằng chứng rõ ràng cho appeal và giúp phát hiện silent degradation trước khi upload.

### 20.11. Hạng mục ưu tiên bổ sung

#### P0

- Scene-state simulator cho Script Engine.
- Channel-level causal/semantic memory.
- Truth-labeling contract.
- Production authenticity audit.
- Rights/provenance ledger.
- AI disclosure decision trong release artifact.

#### P1

- Premise portfolio + selector.
- Visual grammar diversity.
- Cross-video title/thumbnail/voice similarity.
- Calibration suite chứa các false positive đã phát hiện.
- Risk-domain inventory cho toàn bộ channel/account portfolio.

#### P2

- Tự động tạo appeal evidence pack.
- Theo dõi policy version và replay artifact cũ khi policy thay đổi.
- Experiment allocation proven/adjacent/wildcard dựa trên dữ liệu thật.

---

## 21. Kết luận cô đọng

> OmniCast có một production pipeline rộng và nhiều module intelligence riêng lẻ, nhưng chưa có một channel operating system thống nhất.

Các thiếu hụt cốt lõi:

1. Không đo đúng opportunity niche.
2. Không phân tích audiovisual production của đối thủ.
3. Không có chiến lược audience/channel dài hạn điều khiển toàn bộ discovery → packaging → production → analytics.
4. Chưa có multilingual distribution và jurisdiction-aware localization đủ an toàn cho finance/health.
5. Script Engine chưa phân biệt đủ giữa label diversity và causal/narrative diversity.
6. Chưa có production-level authenticity audit để bảo vệ toàn kênh trước chính sách inauthentic content.

Mục tiêu nâng cấp không nên chỉ là thêm nhiều generator. OmniCast cần chuyển từ:

```text
video factory
```

thành:

```text
evidence-driven channel operating system
```

---

## Phụ lục A — Audit & đối chiếu hiện trạng (phiên WS0, 2026-07-25)

> Codex CLI chưa được cài trên máy nên audit này do phiên vận hành Script Engine thực hiện
> theo phương pháp spot-check code (như GPT review 20/07). Khi codex được cài
> (`npm install -g @openai/codex` + `codex login`), nên chạy thêm một lượt audit dòng-máu-OpenAI.

### A.1. Spot-check các claim khả kiểm — 4/4 ĐÚNG

| Claim của brief | Bằng chứng code | Phán quyết |
|---|---|---|
| §5 video_intel placeholder | `video_intel.py:36,49,58` — "cinematic", 150 wpm, hook "question" hard-code | ✅ ĐÚNG |
| §4.1 competitor_intel sort views tuyệt đối | `competitor_intel.py:6,65,82` — "top-N by views", `sort(key=views)` | ✅ ĐÚNG |
| §4.4 comment adapter trả rỗng | `platforms/youtube.py:152-153` — `fetch_comments → return []` | ✅ ĐÚNG |
| §3.2 gap_score double-count demand | `scorer.py:105-123` — "Gap score scales with outlier_ratio" | ✅ ĐÚNG |

### A.2. §19 đã STALE một phần — Script Engine 72h qua (xem `docs/SCRIPT_ENGINE_REVIEW_PACK.md` rev 2 + IMPLEMENTATION_STATUS)

Đối chiếu 8 capability §19.7 với code ngày 25/07:

| Capability §19.7 | Trạng thái | Ghi chú |
|---|---|---|
| 1. Premise portfolio | 🟡 PARTIAL | `distinguishing_turn` + preflight validate + AMBIGUOUS-THREAT STOCK LIST đã ép chất lượng premise; chưa có sinh-8-12-rồi-tuyển |
| 2. Scene-state simulator | 🔴 OPEN | Gap thật — khớp các bài học sống: beat-aliasing, prop-state, "cửa chống thành cửa chốt" |
| 3. Causal fingerprint xuyên video | 🟡 PARTIAL | Mới 2/5 trục (`cross_video.py`), per-run concept fingerprint đủ 5 trục; WS3-P7 đã thiết kế ledger đầy đủ |
| 4. Semantic memory 50-100 truyện | 🔴 OPEN | |
| 5. Near-duplicate hard block | 🟡 PARTIAL | Trong-video: shared-phrase 5-gram + materially-equivalent plans; xuyên-video mới cảnh báo (fail-open có log từ 20/07) |
| 6. Wildcard allocation | 🔴 OPEN | |
| 7. Blind benchmark | 🔴 OPEN | Cần người; 2 AI review (Gemini+GPT 20/07) đã chạy thay thế một phần |
| 8. Calibration set | 🟡 PARTIAL | Fixture false-positive 20260717 + suite 1430 test pin mọi lớp lỗi đã bắt |

Ngoài ra các đề xuất RẢI RÁC trong §19 đã được implement sau external review 20/07:
kiến trúc 3 lớp rule (§19.6) đã hiện thực một phần — **rationed tic chính là soft-signal cấp
lineup** (chỉ chặn occurrence thứ 2 trong compilation, đúng đề xuất); acceptance sửa chữa có
noise band ±1 thay monotonic tuyệt đối; originality có second-judge tiebreak tại biên 6-vs-7;
mệnh lệnh giác quan đồng phục (ears-before-eyes) đã đổi thành menu 5 kênh; audit chống-anchoring
cho distinguishing_turn; finishing wave + Near-Miss Hospital (= "tái chế kịch bản cận đạt" mà
§13 Gemini review đòi). Reviewer đọc §19 nên đối chiếu REVIEW_PACK rev 2 trước khi phán lại.

### A.3. Một bất đồng CÓ BẰNG CHỨNG với §19.6

§19.6 đề xuất "detector phong cách chạy sau prose, không phát blacklist cho writer trước khi
viết". Dữ liệu sống 18/07 (build 0213) chống lại một nửa: recovery chạy 3 LẦN không sửa nổi
tic mà writer không được báo trước; sau khi TEXTURE BUDGETS được khai báo trước trong prompt,
first-draft gate-clean tăng rõ. Đề xuất điều chỉnh: **front-load các RATION đã chứng minh
(ngắn, ổn định), không front-load danh sách mở** — detector sau-prose vẫn là nguồn phát hiện
lớp mới. Đây là điểm cân bằng đã đo được, không phải lựa chọn triết lý.

### A.4. Truth-labeling (§20.4) — NÂNG LÊN HÀNH ĐỘNG P0 KHẨN, CẦN CHỦ KÊNH QUYẾT

Đây là đóng góp giá trị nhất của brief mà mọi tài liệu trước bỏ sót: format hiện tại
("3 TRUE Encounters...", card "REAL ACCOUNTS · NOTHING EXPLAINED") **khẳng định literal truth
cho chuyện hư cấu** — đúng vùng rủi ro inauthentic/manipulation. Hành động cụ thể trước video
kế tiếp: đổi About/description sang khung "dramatized first-person horror, inspired by
real-world situations"; cân nhắc đổi card intro; title "True Encounters" là genre-convention
phổ biến (Mr. Nightmare dùng tương tự) nhưng description KHÔNG được khẳng định "real
submissions". Quyết định branding thuộc chủ kênh.

### A.5. Cross-reference các artifact brief chưa dẫn

- `docs/SCRIPT_ENGINE_REVIEW_PACK.md` (rev 2) — spec engine + 2 external review đã xử lý
- `docs/research/WS2..WS6_*.md` — 5 báo cáo nghiên cứu code-grounded (TTS/topic/render/ops/templating); §5 của brief trùng phần lớn WS4-G3, §3 trùng WS3
- `docs/CHANNEL_IDEAS_Catalog.md` — catalog kênh + policy 2026 (nên merge §20 vào đây hoặc ngược lại, tránh 2 SSOT chính sách)
- `WORKSTREAMS_ParallelUpgrade.md` — charter cách ly + bảng ưu tiên thực thi; mọi roadmap P0-P2 của brief nên nhập vào đây thay vì mở file plan mới (luật vòng đời doc, CLAUDE.md)

### A.6. Ràng buộc vận hành mọi roadmap phải chịu (brief chưa nêu)

1 tài khoản Claude = 1 pipeline LLM tại một thời điểm (đo được: chạy đôi chết đôi) — mọi
capability mới tiêu LLM phải xếp hàng chung batch runner với vòng lặp script đang chạy;
máy phải bật liên tục (batch từng chết vì Windows sleep, 2 lần).
