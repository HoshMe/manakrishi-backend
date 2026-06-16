from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    ROLE_CHOICES = [
        ('farmer', 'Farmer'),
        ('operator', 'Operator'),
        ('dealer', 'Dealer'),
        ('manager', 'Area Manager'),
        ('admin', 'Admin'),
    ]

    phone = models.CharField(max_length=15, unique=True, null=True, blank=True)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='farmer')
    push_token = models.CharField(max_length=255, blank=True)
    language = models.CharField(max_length=5, default='en')
    location_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    location_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    address = models.TextField(blank=True)
    state = models.CharField(max_length=50, blank=True)
    district = models.CharField(max_length=50, blank=True)
    services = models.JSONField(default=list, blank=True)
    login_methods = models.JSONField(default=list, blank=True)
    biometric_devices = models.JSONField(default=list, blank=True)
    is_on_duty = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD = 'phone'
    REQUIRED_FIELDS = ['username']

    def __str__(self):
        return f"{self.get_full_name()} ({self.role})"


class OTP(models.Model):
    phone = models.CharField(max_length=15)
    otp = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']


class Address(models.Model):
    user = models.ForeignKey('User', on_delete=models.CASCADE, related_name='saved_addresses')
    address = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user} - {self.address[:50]}"


class KYCDocument(models.Model):
    DOC_TYPE_CHOICES = [
        ('aadhaar', 'Aadhaar Card'),
        ('pan', 'PAN Card'),
    ]
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    user = models.ForeignKey('User', on_delete=models.CASCADE, related_name='kyc_documents')
    doc_type = models.CharField(max_length=10, choices=DOC_TYPE_CHOICES)
    doc_number = models.CharField(max_length=20, blank=True)
    doc_image = models.ImageField(upload_to='kyc_documents/')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    remarks = models.TextField(blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-uploaded_at']
        unique_together = ['user', 'doc_type']

    def __str__(self):
        return f"{self.user} - {self.get_doc_type_display()} ({self.status})"
