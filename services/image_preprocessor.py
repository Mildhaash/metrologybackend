import cv2

class ImagePreprocessor:
    def preprocess(self, image_path: str) -> str:
        img = cv2.imread(image_path)

        # Only resize large images for speed — no binarization, no heavy filtering
        max_dim = 2000
        h, w = img.shape[:2]
        if max(h, w) > max_dim:
            scale = max_dim / max(h, w)
            img = cv2.resize(img, (int(w * scale), int(h * scale)))

        output_path = image_path.replace('.jpg', '_preprocessed.jpg')
        cv2.imwrite(output_path, img)

        return output_path