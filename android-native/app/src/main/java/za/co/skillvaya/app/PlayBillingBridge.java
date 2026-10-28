package za.co.skillvaya.app;

import android.app.Activity;
import android.util.Base64;
import android.webkit.JavascriptInterface;

import com.android.billingclient.api.*;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Google Play Billing bridge. Entitlements are granted only after the backend verifies
 * the purchase token with the Google Play Developer API.
 */
public final class PlayBillingBridge implements PurchasesUpdatedListener {
    private final Activity activity;
    private final String baseUrl;
    private final ExecutorService io = Executors.newSingleThreadExecutor();
    private BillingClient billingClient;
    private final List<ProductDetails> cachedProducts = new ArrayList<>();
    private String pendingAccountId = "";
    private String pendingAuthToken = "";
    private boolean restoreAfterConnect = false;

    public PlayBillingBridge(Activity activity, String baseUrl) {
        this.activity = activity;
        this.baseUrl = baseUrl == null ? "" : baseUrl.replaceAll("/+$", "");
        billingClient = BillingClient.newBuilder(activity)
            .setListener(this)
            .enablePendingPurchases(PendingPurchasesParams.newBuilder()
                .enableOneTimeProducts()
                .enablePrepaidPlans()
                .build())
            .build();
        connect();
    }

    private void connect() {
        if (billingClient.isReady()) return;
        billingClient.startConnection(new BillingClientStateListener() {
            @Override public void onBillingSetupFinished(BillingResult result) {
                if (result.getResponseCode() == BillingClient.BillingResponseCode.OK) {
                    querySubscriptions();
                    if (restoreAfterConnect) { restoreAfterConnect = false; queryAndRestorePurchases(); }
                } else emit("window.svPlayBillingError", "Google Play Billing could not connect (code " + result.getResponseCode() + ").");
            }
            @Override public void onBillingServiceDisconnected() {
                activity.runOnUiThread(() -> emit("window.svPlayBillingError", "Google Play Billing disconnected. Please retry."));
            }
        });
    }

    @JavascriptInterface
    public void querySubscriptions() {
        if (!billingClient.isReady()) { connect(); return; }
        List<QueryProductDetailsParams.Product> products = new ArrayList<>();
        for (String id : Arrays.asList("skillvaya_local", "skillvaya_priority", "skillvaya_business_plus", "skillvaya_business_spotlight")) {
            products.add(QueryProductDetailsParams.Product.newBuilder()
                .setProductId(id).setProductType(BillingClient.ProductType.SUBS).build());
        }
        QueryProductDetailsParams params = QueryProductDetailsParams.newBuilder().setProductList(products).build();
        billingClient.queryProductDetailsAsync(params, (result, response) -> {
            JSONArray out = new JSONArray();
            synchronized (cachedProducts) {
                cachedProducts.clear();
                for (ProductDetails detail : response.getProductDetailsList()) {
                    cachedProducts.add(detail);
                    JSONArray offers = new JSONArray();
                    List<ProductDetails.SubscriptionOfferDetails> offerDetails = detail.getSubscriptionOfferDetails();
                    if (offerDetails != null) {
                        for (ProductDetails.SubscriptionOfferDetails offer : offerDetails) {
                            JSONObject o = new JSONObject();
                            try {
                                o.put("basePlanId", offer.getBasePlanId());
                                o.put("offerToken", offer.getOfferToken());
                                ProductDetails.PricingPhase phase = offer.getPricingPhases().getPricingPhaseList().get(offer.getPricingPhases().getPricingPhaseList().size()-1);
                                o.put("price", phase.getFormattedPrice());
                                o.put("billingPeriod", phase.getBillingPeriod());
                                o.put("recurrenceMode", phase.getRecurrenceMode());
                                offers.put(o);
                            } catch (Exception ignored) {}
                        }
                    }
                    JSONObject p = new JSONObject();
                    try { p.put("productId", detail.getProductId()); p.put("title", detail.getTitle()); p.put("description", detail.getDescription()); p.put("offers", offers); out.put(p); } catch (Exception ignored) {}
                }
            }
            String js = "window.svPlayBillingProducts && window.svPlayBillingProducts(" + JSONObject.quote(out.toString()) + "," + result.getResponseCode() + ")";
            activity.runOnUiThread(() -> activity.getWindow().getDecorView().post(() -> {
                if (activity instanceof MainActivity) ((MainActivity) activity).runBillingJavascript(js);
            }));
        });
    }

    @JavascriptInterface
    public void purchaseSubscription(String productId, String offerToken, String accountId, String authToken) {
        if (productId == null || offerToken == null || accountId == null || authToken == null ||
            accountId.trim().isEmpty() || authToken.trim().isEmpty()) {
            emit("window.svPlayBillingError", "Please sign in before choosing a Skillvaya subscription.");
            return;
        }
        pendingAccountId = accountId.trim();
        pendingAuthToken = authToken.trim();
        if (!billingClient.isReady()) { connect(); emit("window.svPlayBillingError", "Google Play Billing is connecting. Please try again."); return; }
        ProductDetails selected = null;
        synchronized (cachedProducts) {
            for (ProductDetails p : cachedProducts) if (p.getProductId().equals(productId)) { selected = p; break; }
        }
        if (selected == null) { querySubscriptions(); emit("window.svPlayBillingError", "Subscription price is not loaded yet. Please wait and try again."); return; }
        ProductDetails.SubscriptionOfferDetails selectedOffer = null;
        List<ProductDetails.SubscriptionOfferDetails> offers = selected.getSubscriptionOfferDetails();
        if (offers != null) for (ProductDetails.SubscriptionOfferDetails o : offers) {
            if (o.getOfferToken().equals(offerToken)) { selectedOffer = o; break; }
        }
        if (selectedOffer == null) { querySubscriptions(); emit("window.svPlayBillingError", "This subscription offer expired. Prices are refreshing; please try again."); return; }
        final ProductDetails selectedProduct = selected;
        final ProductDetails.SubscriptionOfferDetails selectedSubscriptionOffer = selectedOffer;
        QueryPurchasesParams existingParams = QueryPurchasesParams.newBuilder().setProductType(BillingClient.ProductType.SUBS).build();
        billingClient.queryPurchasesAsync(existingParams, (result, purchases) -> {
            if (result.getResponseCode() != BillingClient.BillingResponseCode.OK) {
                emit("window.svPlayBillingError", "Could not check your current subscription before checkout. Please retry.");
                return;
            }
            List<Purchase> active = new ArrayList<>();
            boolean pending = false;
            for (Purchase purchase : purchases) {
                if (purchase.getPurchaseState() == Purchase.PurchaseState.PENDING) pending = true;
                else if (purchase.getPurchaseState() == Purchase.PurchaseState.PURCHASED) active.add(purchase);
            }
            if (pending) {
                emit("window.svPlayBillingError", "A Google Play payment is still pending. Wait for it to finish before changing plans.");
                return;
            }
            if (active.size() > 1) {
                emit("window.svPlayBillingError", "More than one active Google Play subscription was found. Manage subscriptions in Google Play before changing plans to avoid duplicate charges.");
                return;
            }
            launchPurchaseFlow(selectedProduct, selectedSubscriptionOffer, active.isEmpty() ? null : active.get(0));
        });
    }

    private void launchPurchaseFlow(ProductDetails selected, ProductDetails.SubscriptionOfferDetails selectedOffer, Purchase existingPurchase) {
        BillingFlowParams.ProductDetailsParams.Builder detailBuilder = BillingFlowParams.ProductDetailsParams.newBuilder()
            .setProductDetails(selected).setOfferToken(selectedOffer.getOfferToken());
        BillingFlowParams.Builder flowBuilder = BillingFlowParams.newBuilder()
            .setObfuscatedAccountId(obfuscatedId(pendingAccountId));
        if (existingPurchase != null) {
            List<String> oldProducts = existingPurchase.getProducts();
            String oldProductId = oldProducts == null || oldProducts.isEmpty() ? "" : oldProducts.get(0);
            int oldRank = productRank(oldProductId);
            int newRank = productRank(selected.getProductId());
            if (oldRank == 0 || newRank == 0) {
                emit("window.svPlayBillingError", "Your current subscription cannot be replaced safely in-app. Manage it in Google Play before choosing another plan.");
                return;
            }
            // Skillvaya uses prepaid, non-auto-renewing base plans. Google Play requires
            // CHARGE_FULL_PRICE when replacing a prepaid plan; proration/deferred modes fail.
            int replacementMode = BillingFlowParams.ProductDetailsParams.SubscriptionProductReplacementParams.ReplacementMode.CHARGE_FULL_PRICE;
            detailBuilder.setSubscriptionProductReplacementParams(BillingFlowParams.ProductDetailsParams.SubscriptionProductReplacementParams.newBuilder()
                .setOldProductId(oldProductId).setReplacementMode(replacementMode).build());
            flowBuilder.setSubscriptionUpdateParams(BillingFlowParams.SubscriptionUpdateParams.newBuilder()
                .setOldPurchaseToken(existingPurchase.getPurchaseToken()).build());
        }
        BillingFlowParams.ProductDetailsParams detailParams = detailBuilder.build();
        BillingFlowParams params = flowBuilder.setProductDetailsParamsList(Arrays.asList(detailParams)).build();
        activity.runOnUiThread(() -> billingClient.launchBillingFlow(activity, params));
    }

    private int productRank(String productId) {
        if ("skillvaya_local".equals(productId)) return 1;
        if ("skillvaya_priority".equals(productId)) return 2;
        if ("skillvaya_business_plus".equals(productId)) return 3;
        if ("skillvaya_business_spotlight".equals(productId)) return 4;
        return 0;
    }

    @JavascriptInterface
    public void restorePurchases(String accountId, String authToken) {
        if (accountId == null || authToken == null || accountId.trim().isEmpty() || authToken.trim().isEmpty()) {
            emit("window.svPlayBillingError", "Sign in before restoring subscriptions.");
            return;
        }
        pendingAccountId = accountId.trim(); pendingAuthToken = authToken.trim();
        if (!billingClient.isReady()) { restoreAfterConnect = true; connect(); return; }
        queryAndRestorePurchases();
    }

    private void queryAndRestorePurchases() {
        QueryPurchasesParams params = QueryPurchasesParams.newBuilder().setProductType(BillingClient.ProductType.SUBS).build();
        billingClient.queryPurchasesAsync(params, (result, purchases) -> {
            if (result.getResponseCode() != BillingClient.BillingResponseCode.OK) {
                emit("window.svPlayBillingError", "Could not restore purchases. Please try again.");
                return;
            }
            for (Purchase purchase : purchases) submitPurchaseForVerification(purchase);
            if (purchases.isEmpty()) emit("window.svPlayBillingResult", "{\"ok\":true,\"restored\":false,\"message\":\"No active Google Play subscriptions were found.\"}");
        });
    }

    @Override public void onPurchasesUpdated(BillingResult result, List<Purchase> purchases) {
        if (result.getResponseCode() == BillingClient.BillingResponseCode.OK && purchases != null) {
            for (Purchase purchase : purchases) submitPurchaseForVerification(purchase);
        } else if (result.getResponseCode() == BillingClient.BillingResponseCode.USER_CANCELED) {
            emit("window.svPlayBillingResult", "{\"ok\":false,\"cancelled\":true,\"message\":\"Purchase cancelled. No charge was made.\"}");
        } else {
            emit("window.svPlayBillingError", "Google Play purchase did not complete (code " + result.getResponseCode() + ").");
        }
    }

    private void submitPurchaseForVerification(Purchase purchase) {
        if (purchase.getPurchaseState() != Purchase.PurchaseState.PURCHASED) {
            emit("window.svPlayBillingResult", "{\"ok\":false,\"pending\":true,\"message\":\"Google Play payment is pending. Access will activate after verification.\"}");
            return;
        }
        io.execute(() -> {
            HttpURLConnection c = null;
            try {
                if (baseUrl.isEmpty()) throw new IllegalStateException("The hosted Skillvaya URL is not configured.");
                URL url = new URL(baseUrl + "/api/google-play/verify");
                c = (HttpURLConnection) url.openConnection();
                c.setRequestMethod("POST"); c.setConnectTimeout(15000); c.setReadTimeout(20000);
                c.setDoOutput(true); c.setRequestProperty("Content-Type", "application/json");
                c.setRequestProperty("Authorization", "Bearer " + pendingAuthToken);
                JSONObject body = new JSONObject();
                body.put("purchase_token", purchase.getPurchaseToken());
                body.put("product_ids", new JSONArray(purchase.getProducts()));
                body.put("order_id", purchase.getOrderId() == null ? "" : purchase.getOrderId());
                try (OutputStream os = c.getOutputStream()) { os.write(body.toString().getBytes(StandardCharsets.UTF_8)); }
                int status = c.getResponseCode();
                java.io.InputStream stream = status >= 200 && status < 400 ? c.getInputStream() : c.getErrorStream();
                java.io.ByteArrayOutputStream buffer = new java.io.ByteArrayOutputStream();
                if (stream != null) { byte[] chunk = new byte[4096]; int count; while ((count = stream.read(chunk)) != -1) buffer.write(chunk, 0, count); }
                String response = new String(buffer.toByteArray(), StandardCharsets.UTF_8);
                if (status >= 200 && status < 300) {
                    JSONObject data = new JSONObject(response);
                    if (data.optBoolean("ok", false)) {
                        if (!purchase.isAcknowledged()) acknowledge(purchase);
                        emit("window.svPlayBillingResult", data.toString());
                    } else emit("window.svPlayBillingError", data.optString("message", "Purchase verification failed. No paid access was granted."));
                } else {
                    JSONObject data;
                    try { data = new JSONObject(response); } catch (Exception ignored) { data = new JSONObject(); }
                    emit("window.svPlayBillingError", data.optString("error", "Skillvaya could not verify this Google Play purchase (HTTP " + status + "). Please retry."));
                }
            } catch (Exception e) {
                emit("window.svPlayBillingError", "Purchase could not be verified yet. Keep the app open and retry from Restore purchases.");
            } finally { if (c != null) c.disconnect(); }
        });
    }

    private void acknowledge(Purchase purchase) {
        billingClient.acknowledgePurchase(AcknowledgePurchaseParams.newBuilder().setPurchaseToken(purchase.getPurchaseToken()).build(),
            result -> { if (result.getResponseCode() != BillingClient.BillingResponseCode.OK) emit("window.svPlayBillingError", "Purchase is verified, but Google Play acknowledgement is pending. Please contact support if this persists."); });
    }

    private String obfuscatedId(String id) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(id.getBytes(StandardCharsets.UTF_8));
            String encoded = Base64.encodeToString(digest, Base64.URL_SAFE | Base64.NO_WRAP | Base64.NO_PADDING);
            return encoded.length() > 64 ? encoded.substring(0, 64) : encoded;
        } catch (Exception e) { return "skillvaya-account"; }
    }

    private void emit(String function, String message) {
        String js = function + "(" + JSONObject.quote(message) + ")";
        activity.runOnUiThread(() -> { if (activity instanceof MainActivity) ((MainActivity) activity).runBillingJavascript(js); });
    }

    public void shutdown() {
        try { io.shutdownNow(); } catch (Exception ignored) {}
        if (billingClient != null) billingClient.endConnection();
    }
}
