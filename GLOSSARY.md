# Content Discovery Layer (内容发现层)

## Language

**灵感目的地 (Inspiration Destination)**:
A venue-neutral destination knowledge card generated from a rule-based city knowledge base (23 destinations), showing suggested days, budget tier, tags, and best season. It is content for inspiring a trip, not a real user trip.
_Avoid_: Destination page, 目的地百科, 城市模板, showcase

**画廊精选 (Gallery Featured)**:
A real user-shared trip that has been marked `is_featured=True` and has a share token. It appears in the public gallery as an inspiratiional item. Only owner can publish their own trip; a staff member can feature any public shared trip.
_Avoid_: 精选行程, Community trip, 推荐行程

**画廊点赞 (Gallery Like)**:
A boolean signal that a logged-in user "likes" a gallery item. Stored independently of the 1-5 star rating and the visited count. It is a binary, non-ranked interaction for community feel; it does not affect the `hot` sort.
_Avoid_: 好评, Upvote, Vote, 收藏

**IsStaff**:
A boolean flag on a user granting them editorial capability over gallery content (feature any public shared trip) without a full admin system.
_Avoid_: Admin, 管理员, Role, ADMIN

**模板深链预填 (Template Deep-link Prefill)**:
A URL form (`/plan?dest=杭州&budget=3000`) that pre-fills the planning form destination and budget when the user arrives from a home-page template card. Days and dates are deliberately not pre-filled: templates carry no real dates, and inventing them would fabricate a travel window.
_Avoid_: 模板深链, 一键创建, Prefill