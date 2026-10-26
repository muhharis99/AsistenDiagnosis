from django.contrib import admin

from payer.models import Coverage, PayerOrganization, PayerPlan, RegistrationCoverage

admin.site.register(PayerOrganization)
admin.site.register(PayerPlan)
admin.site.register(Coverage)
admin.site.register(RegistrationCoverage)
