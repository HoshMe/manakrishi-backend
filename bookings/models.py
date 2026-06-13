from django.db import models
from django.conf import settings


class Booking(models.Model):
    SERVICE_CHOICES = [
        ('drone_spraying', 'Drone Spraying'),
        ('tractor_rental', 'Tractor Rental'),
        ('rotavator', 'Rotavator'),
        ('harvester', 'Harvester'),
        ('seed_drill', 'Seed Drill'),
        ('water_tanker', 'Water Tanker'),
        ('cultivator', 'Cultivator'),
        ('fertilizer_spraying', 'Fertilizer Spraying'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('operator_assigned', 'Operator Assigned'),
        ('on_the_way', 'On The Way'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    booking_id = models.CharField(max_length=20, unique=True, editable=False)
    farmer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='bookings')
    operator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_bookings')
    dealer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='dealer_bookings')

    service = models.CharField(max_length=30, choices=SERVICE_CHOICES)
    crop = models.CharField(max_length=50)
    area_acres = models.DecimalField(max_digits=6, decimal_places=2)
    scheduled_date = models.DateField()
    scheduled_time = models.CharField(max_length=50)
    location_address = models.TextField()
    location_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True)
    location_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True)
    field_photo = models.ImageField(upload_to='field_photos/', blank=True)
    spray_type = models.CharField(max_length=50, blank=True)
    delivery_address = models.TextField(blank=True)
    invoice_address = models.TextField(blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    commission_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.booking_id:
            last = Booking.objects.order_by('-id').first()
            num = (last.id + 1) if last else 1
            self.booking_id = f'MK{10000000 + num}'
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.booking_id} - {self.get_service_display()}"


class Rating(models.Model):
    booking = models.OneToOneField('Booking', on_delete=models.CASCADE, related_name='rating')
    farmer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='given_ratings')
    operator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='received_ratings')
    rating = models.IntegerField()  # 1-5
    review = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.booking.booking_id} - {self.rating} stars"


class Crop(models.Model):
    name = models.CharField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True)
    order = models.IntegerField(default=0)

    class Meta:
        ordering = ['order', 'name']

    def __str__(self):
        return self.name
