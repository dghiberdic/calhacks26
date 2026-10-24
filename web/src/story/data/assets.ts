/** Static files under public/story/ (the Cycles render, the model, the satellite image, rain). */
export const asset = (file: string) => `${import.meta.env.BASE_URL}story/${file}`;
