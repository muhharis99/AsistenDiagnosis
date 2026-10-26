from django.contrib import admin

from claims.models import Claim, ClaimAdjudication, ClaimCollection, ClaimLine

admin.site.register(Claim)
admin.site.register(ClaimLine)
admin.site.register(ClaimAdjudication)
admin.site.register(ClaimCollection)
